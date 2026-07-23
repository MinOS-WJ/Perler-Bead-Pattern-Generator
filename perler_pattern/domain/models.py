from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


HEX_COLOR = re.compile(r"^#[0-9A-F]{6}$")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FitMode(StrEnum):
    FILL_CROP = "fill_crop"
    CONTAIN = "contain"
    STRETCH = "stretch"


class Dithering(StrEnum):
    NONE = "none"
    FLOYD_STEINBERG = "floyd_steinberg"


class ResultState(StrEnum):
    MISSING = "missing"
    CURRENT = "current"
    OUTDATED = "outdated"


@dataclass(slots=True)
class GenerationSettings:
    grid_width: int = 29
    grid_height: int = 29
    max_colors: int = 24
    fit_mode: FitMode = FitMode.FILL_CROP
    color_distance: str = "ciede2000"
    dithering: Dithering = Dithering.NONE
    dither_strength: float = 0.65
    alpha_threshold: int = 16
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    sharpness: float = 1.0
    despeckle_iterations: int = 0
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    result_state: ResultState = ResultState.MISSING

    def __post_init__(self) -> None:
        if not 1 <= self.grid_width <= 500 or not 1 <= self.grid_height <= 500:
            raise ValueError("Grid dimensions must be between 1 and 500")
        if self.grid_width * self.grid_height > 250_000:
            raise ValueError("Grid contains more than 250000 cells")
        if not 1 <= self.max_colors <= 256:
            raise ValueError("Maximum colors must be between 1 and 256")
        if self.color_distance != "ciede2000":
            raise ValueError("Only CIEDE2000 is supported")
        if not 0 <= self.dither_strength <= 1:
            raise ValueError("Dither strength must be between 0 and 1")
        if not 0 <= self.alpha_threshold <= 255:
            raise ValueError("Alpha threshold must be between 0 and 255")
        for value, label in (
            (self.brightness, "Brightness"),
            (self.contrast, "Contrast"),
        ):
            if not 0.1 <= value <= 3:
                raise ValueError(f"{label} must be between 0.1 and 3")
        if not 0 <= self.saturation <= 3:
            raise ValueError("Saturation must be between 0 and 3")
        if not 0 <= self.sharpness <= 5:
            raise ValueError("Sharpness must be between 0 and 5")
        if not 0 <= self.despeckle_iterations <= 8:
            raise ValueError("Despeckle iterations must be between 0 and 8")
        if self.rotation not in {0, 90, 180, 270}:
            raise ValueError("Rotation must be 0, 90, 180 or 270")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["fit_mode"] = self.fit_mode.value
        data["dithering"] = self.dithering.value
        data["result_state"] = self.result_state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationSettings:
        values = dict(data)
        values["fit_mode"] = FitMode(values.get("fit_mode", FitMode.FILL_CROP))
        values["dithering"] = Dithering(values.get("dithering", Dithering.NONE))
        values["result_state"] = ResultState(
            values.get("result_state", ResultState.MISSING)
        )
        return cls(**values)


@dataclass(slots=True)
class BoardSettings:
    width: int = 29
    height: int = 29

    def __post_init__(self) -> None:
        if not 1 <= self.width <= 100 or not 1 <= self.height <= 100:
            raise ValueError("Board dimensions must be between 1 and 100")


@dataclass(slots=True)
class ViewSettings:
    active_tab: str = "source"
    show_grid: bool = True
    show_codes: bool = True
    zoom_percent: int = 100
    left_panel_visible: bool = True
    right_panel_visible: bool = True

    def __post_init__(self) -> None:
        if self.active_tab not in {"source", "preview"}:
            raise ValueError("Invalid active document tab")
        if not 10 <= self.zoom_percent <= 800:
            raise ValueError("Zoom must be between 10 and 800")


@dataclass(slots=True)
class ProjectMetadata:
    title: str = "未命名图纸"
    author: str = ""
    notes: str = ""
    created_at: str = field(default_factory=utc_now)
    modified_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        self.title = self.title.strip() or "未命名图纸"
        self.author = self.author.strip()
        if len(self.title) > 120:
            raise ValueError("Project title is too long")
        if len(self.author) > 80:
            raise ValueError("Project author is too long")
        if len(self.notes) > 4000:
            raise ValueError("Project notes are too long")


@dataclass(slots=True)
class PaletteColor:
    code: str
    name: str
    hex: str
    enabled: bool = True
    stock: int | None = None

    def __post_init__(self) -> None:
        self.code = self.code.strip().upper()
        self.name = self.name.strip()
        self.hex = self.hex.strip().upper()
        if not 1 <= len(self.code) <= 32:
            raise ValueError("Palette color code must contain 1 to 32 characters")
        if not 1 <= len(self.name) <= 80:
            raise ValueError("Palette color name must contain 1 to 80 characters")
        if not HEX_COLOR.fullmatch(self.hex):
            raise ValueError(f"Invalid palette color: {self.hex}")
        if self.stock is not None and self.stock < 0:
            raise ValueError("Palette stock cannot be negative")

    @property
    def rgb(self) -> tuple[int, int, int]:
        return tuple(int(self.hex[index : index + 2], 16) for index in (1, 3, 5))


@dataclass(slots=True)
class Palette:
    id: str
    name: str
    colors: list[PaletteColor]

    def __post_init__(self) -> None:
        self.id = self.id.strip()
        self.name = self.name.strip()
        if not self.id or not self.name:
            raise ValueError("Palette id and name are required")
        if not 1 <= len(self.colors) <= 1024:
            raise ValueError("Palette must contain 1 to 1024 colors")
        codes = [color.code.casefold() for color in self.colors]
        if len(codes) != len(set(codes)):
            raise ValueError("Palette color codes must be unique")
        if not any(color.enabled for color in self.colors):
            raise ValueError("At least one palette color must be enabled")

    @property
    def enabled_colors(self) -> list[PaletteColor]:
        return [color for color in self.colors if color.enabled]

    def color_by_code(self, code: str) -> PaletteColor:
        folded = code.casefold()
        for color in self.colors:
            if color.code.casefold() == folded:
                return color
        raise KeyError(code)


@dataclass(slots=True)
class SourceImage:
    data: bytes
    original_name: str
    media_type: str
    width: int
    height: int
    extension: str
    exif_orientation_applied: bool = True

    def __post_init__(self) -> None:
        self.original_name = Path(self.original_name).name
        self.extension = self.extension.lower()
        if self.extension not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            raise ValueError("Unsupported source image extension")
        if not self.data or self.width < 1 or self.height < 1:
            raise ValueError("Source image is empty")


@dataclass(frozen=True, slots=True)
class PatternGrid:
    width: int
    height: int
    palette_codes: tuple[str, ...]
    cells: tuple[tuple[int, ...], ...]
    generated_at: str
    input_fingerprint: str
    manually_edited: bool = False
    edited_at: str | None = None

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("Pattern grid dimensions must be positive")
        if len(self.cells) != self.height:
            raise ValueError("Pattern grid row count does not match height")
        for row in self.cells:
            if len(row) != self.width:
                raise ValueError("Pattern grid column count does not match width")
            if any(value < -1 or value >= len(self.palette_codes) for value in row):
                raise ValueError("Pattern grid contains an invalid palette index")
        if len(set(code.casefold() for code in self.palette_codes)) != len(
            self.palette_codes
        ):
            raise ValueError("Pattern grid palette codes must be unique")
        if self.manually_edited and not self.edited_at:
            raise ValueError("Manually edited grids require edited_at")
        if not self.manually_edited and self.edited_at is not None:
            raise ValueError("Unedited grids cannot contain edited_at")

    @property
    def bead_count(self) -> int:
        return sum(value >= 0 for row in self.cells for value in row)

    def counts_by_code(self) -> dict[str, int]:
        counts = {code: 0 for code in self.palette_codes}
        for row in self.cells:
            for value in row:
                if value >= 0:
                    counts[self.palette_codes[value]] += 1
        return counts


@dataclass(frozen=True, slots=True)
class UsageItem:
    code: str
    name: str
    hex: str
    quantity: int
    stock: int | None
    shortage: int | None


@dataclass(frozen=True, slots=True)
class UsageSummary:
    items: tuple[UsageItem, ...]
    total_beads: int
    used_colors: int
    board_count: int


@dataclass(slots=True)
class Project:
    id: str
    metadata: ProjectMetadata
    generation: GenerationSettings
    view: ViewSettings
    palette: Palette
    boards: BoardSettings
    source: SourceImage | None = None
    grid: PatternGrid | None = None
    preview_png: bytes | None = None
    export_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    path: Path | None = None
    dirty: bool = False

    @classmethod
    def new(cls, palette: Palette) -> Project:
        return cls(
            id=str(uuid.uuid4()),
            metadata=ProjectMetadata(),
            generation=GenerationSettings(),
            view=ViewSettings(),
            palette=palette,
            boards=BoardSettings(),
            export_settings={
                "png": {
                    "scale": 4,
                    "show_grid": True,
                    "show_codes": True,
                    "background": "#FFFFFF",
                },
                "svg": {
                    "show_grid": True,
                    "show_codes": True,
                    "include_legend": True,
                },
                "pdf": {
                    "page_size": "A4",
                    "orientation": "auto",
                    "include_overview": True,
                    "include_board_pages": True,
                    "include_legend": True,
                },
            },
        )

    def touch(self, *, pattern_outdated: bool = False) -> None:
        self.metadata.modified_at = utc_now()
        self.dirty = True
        if pattern_outdated and self.grid is not None:
            self.generation.result_state = ResultState.OUTDATED

    def set_source(self, source: SourceImage) -> None:
        self.source = source
        self.metadata.title = Path(source.original_name).stem or self.metadata.title
        self.grid = None
        self.preview_png = None
        self.generation.result_state = ResultState.MISSING
        self.touch()

    def set_generation_settings(self, settings: GenerationSettings) -> None:
        state = ResultState.OUTDATED if self.grid is not None else ResultState.MISSING
        self.generation = replace(settings, result_state=state)
        self.touch()

    def set_palette(self, palette: Palette) -> None:
        self.palette = palette
        self.touch(pattern_outdated=True)

    def set_grid(self, grid: PatternGrid, preview_png: bytes | None = None) -> None:
        self._validate_grid(grid)
        self.grid = grid
        self.preview_png = preview_png
        self.generation.result_state = ResultState.CURRENT
        self.touch()

    def apply_manual_edit(self, grid: PatternGrid) -> None:
        if self.grid is None or self.generation.result_state is not ResultState.CURRENT:
            raise ValueError("Only a current pattern can be edited")
        self._validate_grid(grid)
        self.grid = grid
        self.preview_png = None
        self.touch()

    def _validate_grid(self, grid: PatternGrid) -> None:
        if grid.width != self.generation.grid_width or grid.height != self.generation.grid_height:
            raise ValueError("Pattern grid does not match generation dimensions")
        palette_codes = {color.code.casefold() for color in self.palette.colors}
        if any(code.casefold() not in palette_codes for code in grid.palette_codes):
            raise ValueError("Pattern grid references a missing palette color")

    def input_fingerprint(self) -> str:
        if self.source is None:
            return ""
        payload = {
            "source_sha256": hashlib.sha256(self.source.data).hexdigest(),
            "generation": {
                key: value
                for key, value in self.generation.to_dict().items()
                if key != "result_state"
            },
            "palette": [
                {"code": color.code, "hex": color.hex}
                for color in self.palette.colors
                if color.enabled
            ],
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    def usage_summary(self) -> UsageSummary:
        if self.grid is None:
            return UsageSummary((), 0, 0, 0)
        counts = self.grid.counts_by_code()
        items: list[UsageItem] = []
        for color in self.palette.colors:
            quantity = counts.get(color.code, 0)
            if quantity == 0:
                continue
            shortage = None if color.stock is None else max(quantity - color.stock, 0)
            items.append(
                UsageItem(
                    code=color.code,
                    name=color.name,
                    hex=color.hex,
                    quantity=quantity,
                    stock=color.stock,
                    shortage=shortage,
                )
            )
        horizontal = (self.grid.width + self.boards.width - 1) // self.boards.width
        vertical = (self.grid.height + self.boards.height - 1) // self.boards.height
        return UsageSummary(
            items=tuple(items),
            total_beads=self.grid.bead_count,
            used_colors=len(items),
            board_count=horizontal * vertical,
        )
