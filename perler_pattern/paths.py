from __future__ import annotations

import sys
import os
from pathlib import Path


def workspace_root() -> Path:
    anchor = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    for parent in (anchor.parent, *anchor.parents):
        if (parent / "main.py").is_file() and (parent / "perler_pattern" / "resources").is_dir():
            return parent
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def application_data_directory() -> Path:
    override = os.environ.get("PBPG_DATA_DIRECTORY")
    if override:
        candidate = Path(override).resolve()
        root = workspace_root().resolve()
        if candidate == root or root in candidate.parents:
            return candidate
        raise ValueError("PBPG_DATA_DIRECTORY 必须位于项目目录内")
    return workspace_root() / ".pbpg_data"


def icon_path(name: str) -> Path:
    development = workspace_root() / "perler_pattern" / "resources" / "icons" / name
    if development.is_file():
        return development
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return bundle_root / "perler_pattern" / "resources" / "icons" / name
