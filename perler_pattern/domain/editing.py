from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from perler_pattern.domain.models import PatternGrid, utc_now


class EditTool(StrEnum):
    BRUSH = "brush"
    ERASER = "eraser"
    PICKER = "picker"


@dataclass(frozen=True, slots=True)
class CellChange:
    row: int
    column: int
    before: int
    after: int


@dataclass(frozen=True, slots=True)
class EditCommand:
    tool: EditTool
    changes: tuple[CellChange, ...]
    created_at: str


class PatternEditSession:
    def __init__(
        self,
        grid: PatternGrid,
        *,
        maximum_commands: int = 100,
        maximum_cell_changes: int = 1_000_000,
    ) -> None:
        if maximum_commands < 1 or maximum_cell_changes < 1:
            raise ValueError("Edit history limits must be positive")
        self.maximum_commands = maximum_commands
        self.maximum_cell_changes = maximum_cell_changes
        self.reset(grid)

    def reset(self, grid: PatternGrid) -> None:
        self.width = grid.width
        self.height = grid.height
        self.palette_codes = list(grid.palette_codes)
        self.cells = [list(row) for row in grid.cells]
        self.generated_at = grid.generated_at
        self.input_fingerprint = grid.input_fingerprint
        self.base_manually_edited = grid.manually_edited
        self.base_edited_at = grid.edited_at
        self.undo_stack: list[EditCommand] = []
        self.redo_stack: list[EditCommand] = []
        self._active_tool: EditTool | None = None
        self._active_changes: dict[tuple[int, int], CellChange] = {}

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def begin_stroke(self, tool: EditTool) -> None:
        if tool is EditTool.PICKER:
            raise ValueError("Picker does not create edit commands")
        if self._active_tool is not None:
            raise RuntimeError("An edit stroke is already active")
        self._active_tool = tool
        self._active_changes = {}

    def apply_cell(self, row: int, column: int, palette_code: str | None) -> bool:
        if self._active_tool is None:
            raise RuntimeError("No edit stroke is active")
        self._validate_coordinate(row, column)
        replacement = -1 if self._active_tool is EditTool.ERASER else self._palette_index(palette_code)
        current = self.cells[row][column]
        if current == replacement:
            return False
        key = (row, column)
        original = self._active_changes[key].before if key in self._active_changes else current
        self.cells[row][column] = replacement
        if original == replacement:
            self._active_changes.pop(key, None)
        else:
            self._active_changes[key] = CellChange(row, column, original, replacement)
        return True

    def apply_line(
        self,
        start_row: int,
        start_column: int,
        end_row: int,
        end_column: int,
        palette_code: str | None,
    ) -> int:
        changed = 0
        for row, column in self.line_cells(start_row, start_column, end_row, end_column):
            changed += self.apply_cell(row, column, palette_code)
        return changed

    def end_stroke(self) -> EditCommand | None:
        if self._active_tool is None:
            raise RuntimeError("No edit stroke is active")
        command = None
        if self._active_changes:
            command = EditCommand(
                tool=self._active_tool,
                changes=tuple(self._active_changes.values()),
                created_at=utc_now(),
            )
            self.undo_stack.append(command)
            self.redo_stack.clear()
            self._trim_history()
        self._active_tool = None
        self._active_changes = {}
        return command

    def cancel_stroke(self) -> None:
        if self._active_tool is None:
            return
        for change in self._active_changes.values():
            self.cells[change.row][change.column] = change.before
        self._active_tool = None
        self._active_changes = {}

    def undo(self) -> bool:
        if self._active_tool is not None:
            raise RuntimeError("Cannot undo during an active stroke")
        if not self.undo_stack:
            return False
        command = self.undo_stack.pop()
        for change in command.changes:
            self.cells[change.row][change.column] = change.before
        self.redo_stack.append(command)
        return True

    def redo(self) -> bool:
        if self._active_tool is not None:
            raise RuntimeError("Cannot redo during an active stroke")
        if not self.redo_stack:
            return False
        command = self.redo_stack.pop()
        for change in command.changes:
            self.cells[change.row][change.column] = change.after
        self.undo_stack.append(command)
        return True

    def pick_code(self, row: int, column: int) -> str | None:
        self._validate_coordinate(row, column)
        value = self.cells[row][column]
        return None if value < 0 else self.palette_codes[value]

    def to_grid(self) -> PatternGrid:
        edited = self.base_manually_edited or bool(self.undo_stack)
        edited_at = self.undo_stack[-1].created_at if self.undo_stack else self.base_edited_at
        return PatternGrid(
            width=self.width,
            height=self.height,
            palette_codes=tuple(self.palette_codes),
            cells=tuple(tuple(row) for row in self.cells),
            generated_at=self.generated_at,
            input_fingerprint=self.input_fingerprint,
            manually_edited=edited,
            edited_at=edited_at if edited else None,
        )

    def _palette_index(self, palette_code: str | None) -> int:
        if not palette_code:
            raise ValueError("Brush requires a palette color")
        folded = palette_code.casefold()
        for index, code in enumerate(self.palette_codes):
            if code.casefold() == folded:
                return index
        self.palette_codes.append(palette_code)
        return len(self.palette_codes) - 1

    def _validate_coordinate(self, row: int, column: int) -> None:
        if not 0 <= row < self.height or not 0 <= column < self.width:
            raise IndexError("Grid coordinate is outside the pattern")

    def _trim_history(self) -> None:
        total_changes = sum(len(command.changes) for command in self.undo_stack)
        while self.undo_stack and (
            len(self.undo_stack) > self.maximum_commands
            or total_changes > self.maximum_cell_changes
        ):
            removed = self.undo_stack.pop(0)
            total_changes -= len(removed.changes)

    @staticmethod
    def line_cells(
        start_row: int,
        start_column: int,
        end_row: int,
        end_column: int,
    ) -> tuple[tuple[int, int], ...]:
        column = start_column
        row = start_row
        delta_column = abs(end_column - start_column)
        delta_row = -abs(end_row - start_row)
        column_step = 1 if start_column < end_column else -1
        row_step = 1 if start_row < end_row else -1
        error = delta_column + delta_row
        result: list[tuple[int, int]] = []
        while True:
            result.append((row, column))
            if column == end_column and row == end_row:
                break
            doubled = 2 * error
            if doubled >= delta_row:
                error += delta_row
                column += column_step
            if doubled <= delta_column:
                error += delta_column
                row += row_step
        return tuple(result)
