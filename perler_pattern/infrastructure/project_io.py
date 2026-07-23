from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any

from perler_pattern import __version__
from perler_pattern.domain.models import (
    BoardSettings,
    GenerationSettings,
    Palette,
    PaletteColor,
    PatternGrid,
    Project,
    ProjectMetadata,
    ResultState,
    SourceImage,
    ViewSettings,
)


FORMAT_NAME = "perler-pattern-project"
FORMAT_VERSION = 2
MAX_ENTRIES = 32
MAX_ENTRY_SIZE = 256 * 1024 * 1024
MAX_TOTAL_SIZE = 512 * 1024 * 1024
SOURCE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class ProjectFormatError(ValueError):
    pass


class ProjectSaveError(OSError):
    def __init__(self, message: str, temporary_path: Path | None = None) -> None:
        super().__init__(message)
        self.temporary_path = temporary_path


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _serialize_project(project: Project) -> dict[str, Any]:
    source_data: dict[str, Any] = {}
    if project.source is not None:
        source_data = {
            "entry": f"source/image{project.source.extension}",
            "original_name": project.source.original_name,
            "media_type": project.source.media_type,
            "width": project.source.width,
            "height": project.source.height,
            "exif_orientation_applied": project.source.exif_orientation_applied,
        }
    return {
        "metadata": asdict(project.metadata),
        "source": source_data,
        "generation": project.generation.to_dict(),
        "view": asdict(project.view),
        "palette": {
            "id": project.palette.id,
            "name": project.palette.name,
            "colors": [asdict(color) for color in project.palette.colors],
        },
        "boards": asdict(project.boards),
        "exports": project.export_settings,
    }


def _serialize_grid(grid: PatternGrid) -> dict[str, Any]:
    return {
        "width": grid.width,
        "height": grid.height,
        "palette_codes": list(grid.palette_codes),
        "cells": [list(row) for row in grid.cells],
        "generated_at": grid.generated_at,
        "input_fingerprint": grid.input_fingerprint,
        "manually_edited": grid.manually_edited,
        "edited_at": grid.edited_at,
    }


def _build_entries(project: Project) -> dict[str, bytes]:
    entries = {"project.json": _json_bytes(_serialize_project(project))}
    if project.source is not None:
        entries[f"source/image{project.source.extension}"] = project.source.data
    if project.grid is not None:
        entries["pattern/grid.json"] = _json_bytes(_serialize_grid(project.grid))
    if project.preview_png:
        entries["preview/preview.png"] = project.preview_png
    return entries


def _manifest(project: Project, entries: dict[str, bytes], recovery_for: str | None) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "project_id": project.id,
        "created_at": project.metadata.created_at,
        "modified_at": project.metadata.modified_at,
        "entries": {
            name: {"size": len(data), "sha256": _hash(data)}
            for name, data in entries.items()
        },
    }
    if recovery_for is not None:
        manifest["recovery_for"] = recovery_for
    return manifest


def _write_archive(path: Path, project: Project, recovery_for: str | None) -> None:
    entries = _build_entries(project)
    manifest_data = _json_bytes(_manifest(project, entries, recovery_for))
    with path.open("xb") as raw_file:
        with zipfile.ZipFile(raw_file, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", manifest_data)
            for name, data in entries.items():
                archive.writestr(name, data)
        raw_file.flush()
        os.fsync(raw_file.fileno())


def save_project(
    project: Project,
    path: str | Path,
    *,
    recovery_for: str | None = None,
) -> Path:
    target = Path(path)
    if target.suffix.casefold() != ".pbpg":
        target = target.with_suffix(".pbpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        _write_archive(temporary, project, recovery_for)
        load_project(temporary, allow_temporary=True)
        os.replace(temporary, target)
        if os.name != "nt":
            directory_handle = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory_handle)
            finally:
                os.close(directory_handle)
    except ProjectFormatError as error:
        if temporary.exists():
            temporary.unlink()
        raise ProjectSaveError(f"临时工程校验失败：{error}") from error
    except OSError as error:
        raise ProjectSaveError(
            f"无法保存工程：{error}",
            temporary_path=temporary if temporary.exists() else None,
        ) from error
    if recovery_for is None:
        project.path = target
        project.dirty = False
    return target


def _safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and "\\" not in name
        and not path.is_absolute()
        and ".." not in path.parts
        and "." not in path.parts
    )


def _read_archive(path: Path) -> tuple[dict[str, Any], dict[str, bytes], list[str]]:
    warnings: list[str] = []
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise ProjectFormatError(f"不是有效的 PBPG 工程：{error}") from error
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ProjectFormatError("工程条目数量超过 32")
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise ProjectFormatError("工程包含重复 ZIP 条目")
        total_size = 0
        for info in infos:
            if not _safe_name(info.filename):
                raise ProjectFormatError(f"工程包含不安全路径：{info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ProjectFormatError(f"工程包含符号链接：{info.filename}")
            if info.file_size > MAX_ENTRY_SIZE:
                raise ProjectFormatError(f"工程条目过大：{info.filename}")
            total_size += info.file_size
        if total_size > MAX_TOTAL_SIZE:
            raise ProjectFormatError("工程解压后大小超过 512 MiB")
        if "manifest.json" not in names:
            raise ProjectFormatError("工程缺少 manifest.json")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (json.JSONDecodeError, UnicodeDecodeError, RuntimeError) as error:
            raise ProjectFormatError("manifest.json 无效") from error
        if not isinstance(manifest, dict):
            raise ProjectFormatError("manifest.json 顶层必须是对象")
        if manifest.get("format") != FORMAT_NAME:
            raise ProjectFormatError("工程格式标识不匹配")
        if manifest.get("format_version") == 1:
            raise ProjectFormatError("不兼容的旧工程格式（格式版本 1）")
        if manifest.get("format_version") != FORMAT_VERSION:
            raise ProjectFormatError("不支持的工程格式版本")
        declared = manifest.get("entries")
        if not isinstance(declared, dict):
            raise ProjectFormatError("manifest 缺少 entries")
        payloads: dict[str, bytes] = {}
        for name, metadata in declared.items():
            if name not in names or name == "manifest.json" or not _safe_name(name):
                raise ProjectFormatError(f"manifest 声明了无效条目：{name}")
            if not isinstance(metadata, dict):
                raise ProjectFormatError(f"manifest 条目无效：{name}")
            data = archive.read(name)
            valid = metadata.get("size") == len(data) and metadata.get("sha256") == _hash(data)
            if not valid and name == "preview/preview.png":
                warnings.append("缓存预览校验失败，已忽略")
                continue
            if not valid:
                raise ProjectFormatError(f"工程条目校验失败：{name}")
            payloads[name] = data
        return manifest, payloads, warnings


def _mapping(data: Any, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ProjectFormatError(f"{label} 必须是对象")
    return data


def _decode_json(data: bytes, label: str) -> dict[str, Any]:
    try:
        return _mapping(json.loads(data), label)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProjectFormatError(f"{label} 不是有效 JSON") from error


def _deserialize_project(
    manifest: dict[str, Any], payloads: dict[str, bytes], path: Path
) -> Project:
    if "project.json" not in payloads:
        raise ProjectFormatError("工程缺少 project.json")
    data = _decode_json(payloads["project.json"], "project.json")
    try:
        project_id = str(manifest["project_id"])
        uuid.UUID(project_id)
        metadata = ProjectMetadata(**_mapping(data["metadata"], "metadata"))
        generation = GenerationSettings.from_dict(_mapping(data["generation"], "generation"))
        view = ViewSettings(**_mapping(data["view"], "view"))
        palette_data = _mapping(data["palette"], "palette")
        colors = [PaletteColor(**item) for item in palette_data["colors"]]
        palette = Palette(
            id=str(palette_data["id"]),
            name=str(palette_data["name"]),
            colors=colors,
        )
        boards = BoardSettings(**_mapping(data["boards"], "boards"))
        source_info = _mapping(data.get("source", {}), "source")
        source = None
        if source_info:
            entry = str(source_info["entry"])
            extension = PurePosixPath(entry).suffix.casefold()
            if entry != f"source/image{extension}" or extension not in SOURCE_EXTENSIONS:
                raise ProjectFormatError("源图条目路径无效")
            if entry not in payloads:
                raise ProjectFormatError("工程缺少嵌入源图")
            source = SourceImage(
                data=payloads[entry],
                original_name=str(source_info["original_name"]),
                media_type=str(source_info["media_type"]),
                width=int(source_info["width"]),
                height=int(source_info["height"]),
                extension=extension,
                exif_orientation_applied=bool(source_info.get("exif_orientation_applied", True)),
            )
        grid = None
        if "pattern/grid.json" in payloads:
            grid_data = _decode_json(payloads["pattern/grid.json"], "pattern/grid.json")
            grid = PatternGrid(
                width=int(grid_data["width"]),
                height=int(grid_data["height"]),
                palette_codes=tuple(str(code) for code in grid_data["palette_codes"]),
                cells=tuple(tuple(int(value) for value in row) for row in grid_data["cells"]),
                generated_at=str(grid_data["generated_at"]),
                input_fingerprint=str(grid_data["input_fingerprint"]),
                manually_edited=bool(grid_data.get("manually_edited", False)),
                edited_at=str(grid_data["edited_at"]) if grid_data.get("edited_at") else None,
            )
        project = Project(
            id=project_id,
            metadata=metadata,
            generation=generation,
            view=view,
            palette=palette,
            boards=boards,
            source=source,
            grid=grid,
            preview_png=payloads.get("preview/preview.png"),
            export_settings=_mapping(data.get("exports", {}), "exports"),
            path=path,
            dirty=False,
        )
        if grid is not None:
            project.set_grid(grid, project.preview_png)
            project.dirty = False
            if grid.input_fingerprint != project.input_fingerprint():
                project.generation.result_state = ResultState.OUTDATED
        elif project.generation.result_state is not ResultState.MISSING:
            project.generation.result_state = ResultState.MISSING
        return project
    except ProjectFormatError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ProjectFormatError(f"project.json 内容无效：{error}") from error


def load_project(path: str | Path, *, allow_temporary: bool = False) -> Project:
    project_path = Path(path)
    if not allow_temporary and project_path.suffix.casefold() != ".pbpg":
        raise ProjectFormatError("工程扩展名必须是 .pbpg")
    manifest, payloads, _warnings = _read_archive(project_path)
    return _deserialize_project(manifest, payloads, project_path)


def read_manifest(path: str | Path) -> dict[str, Any]:
    manifest, _payloads, _warnings = _read_archive(Path(path))
    return manifest
