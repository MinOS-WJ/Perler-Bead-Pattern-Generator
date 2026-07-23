from __future__ import annotations

import csv
import hashlib
import io
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from perler_pattern.domain.models import Palette, PaletteColor


class PaletteFormatError(ValueError):
    pass


def _palette_from_mapping(data: dict[str, Any], *, fallback_id: str) -> Palette:
    try:
        colors_data = data["colors"]
        if not isinstance(colors_data, list):
            raise TypeError("colors must be a list")
        colors = [PaletteColor(**item) for item in colors_data]
        return Palette(
            id=str(data.get("id") or fallback_id),
            name=str(data.get("name") or "自定义色板"),
            colors=colors,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise PaletteFormatError(f"色板 JSON 无效：{error}") from error


def load_default_palette() -> Palette:
    resource = files("perler_pattern.resources").joinpath("neutral_palette.json")
    data = json.loads(resource.read_text(encoding="utf-8"))
    return _palette_from_mapping(data, fallback_id="neutral-default")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PaletteFormatError("色板文件必须使用 UTF-8、UTF-8 BOM 或 GB18030 编码")


def _parse_bool(value: str, *, row: int) -> bool:
    normalized = value.strip().casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise PaletteFormatError(f"第 {row} 行 enabled 不是有效布尔值")


def _load_csv(path: Path) -> Palette:
    text = _read_text(path)
    reader = csv.DictReader(io.StringIO(text))
    required = {"code", "name", "hex"}
    fields = {field.strip() for field in (reader.fieldnames or []) if field}
    if not required.issubset(fields):
        raise PaletteFormatError("CSV 必须包含 code、name、hex 列")
    colors: list[PaletteColor] = []
    try:
        for row_number, row in enumerate(reader, start=2):
            enabled_text = (row.get("enabled") or "true").strip()
            stock_text = (row.get("stock") or "").strip()
            colors.append(
                PaletteColor(
                    code=row.get("code") or "",
                    name=row.get("name") or "",
                    hex=row.get("hex") or "",
                    enabled=_parse_bool(enabled_text, row=row_number),
                    stock=int(stock_text) if stock_text else None,
                )
            )
    except (TypeError, ValueError) as error:
        raise PaletteFormatError(f"色板 CSV 无效：{error}") from error
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    try:
        return Palette(id=f"imported-{digest}", name=path.stem, colors=colors)
    except ValueError as error:
        raise PaletteFormatError(f"色板 CSV 无效：{error}") from error


def load_palette(path: str | Path) -> Palette:
    palette_path = Path(path)
    suffix = palette_path.suffix.casefold()
    if suffix == ".csv":
        return _load_csv(palette_path)
    if suffix == ".json":
        try:
            text = _read_text(palette_path)
            data = json.loads(text)
            if not isinstance(data, dict):
                raise TypeError("root must be an object")
        except (json.JSONDecodeError, TypeError) as error:
            raise PaletteFormatError(f"色板 JSON 无效：{error}") from error
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        return _palette_from_mapping(data, fallback_id=f"imported-{digest}")
    raise PaletteFormatError("仅支持 JSON 或 CSV 色板")
