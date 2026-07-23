from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from perler_pattern.domain.models import Project
from perler_pattern.infrastructure.project_io import (
    ProjectFormatError,
    load_project,
    read_manifest,
    save_project,
)


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    path: Path
    recovery_for: Path | None
    project_id: str
    modified_at: str
    title: str


class RecoveryStore:
    def __init__(self, data_directory: str | Path) -> None:
        self.data_directory = Path(data_directory)
        self.autosave_directory = self.data_directory / "autosave"

    def path_for(self, project: Project) -> Path:
        if project.path is not None:
            return project.path.parent / f".{project.path.name}.autosave.pbpg"
        return self.autosave_directory / f"untitled-{project.id}.autosave.pbpg"

    def save(self, project: Project) -> Path:
        target = self.path_for(project)
        recovery_for = str(project.path.resolve()) if project.path is not None else None
        return save_project(project, target, recovery_for=recovery_for)

    def clear(self, project: Project) -> bool:
        path = self.path_for(project)
        if not path.exists():
            return False
        path.unlink()
        return True

    def candidate(self, path: str | Path) -> RecoveryCandidate:
        recovery_path = Path(path)
        manifest = read_manifest(recovery_path)
        project = load_project(recovery_path)
        recovery_for = manifest.get("recovery_for")
        return RecoveryCandidate(
            path=recovery_path,
            recovery_for=Path(recovery_for) if recovery_for else None,
            project_id=project.id,
            modified_at=project.metadata.modified_at,
            title=project.metadata.title,
        )

    def scan(self, additional_paths: tuple[Path, ...] = ()) -> tuple[list[RecoveryCandidate], list[Path]]:
        paths: set[Path] = set(additional_paths)
        if self.autosave_directory.exists():
            paths.update(self.autosave_directory.glob("untitled-*.autosave.pbpg"))
        candidates: list[RecoveryCandidate] = []
        invalid: list[Path] = []
        for path in sorted(paths, key=str):
            try:
                candidates.append(self.candidate(path))
            except (OSError, ProjectFormatError):
                invalid.append(path)
        candidates.sort(key=lambda item: item.modified_at, reverse=True)
        return candidates, invalid

    @staticmethod
    def stale_candidates(candidates: list[RecoveryCandidate]) -> list[RecoveryCandidate]:
        cutoff = datetime.now(UTC) - timedelta(days=30)
        stale: list[RecoveryCandidate] = []
        for candidate in candidates:
            if candidate.recovery_for is not None and candidate.recovery_for.exists():
                continue
            try:
                modified = datetime.fromisoformat(candidate.modified_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if modified < cutoff:
                stale.append(candidate)
        return stale
