from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPaintEvent, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from perler_pattern.domain.editing import EditTool, PatternEditSession
from perler_pattern.domain.models import Palette


class PatternCanvas(QWidget):
    stroke_committed = Signal()
    color_picked = Signal(str)
    coordinate_hovered = Signal(int, int)
    zoom_requested = Signal(int)

    BASE_CELL_SIZE = 24

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PatternCanvas")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.session: PatternEditSession | None = None
        self.palette: Palette | None = None
        self.tool = EditTool.BRUSH
        self.selected_color: str | None = None
        self.zoom_percent = 100
        self.show_grid = True
        self.show_codes = True
        self.interaction_enabled = False
        self._hovered_cell: tuple[int, int] | None = None
        self._last_stroke_cell: tuple[int, int] | None = None
        self._stroke_active = False
        self._resize_to_pattern()

    @property
    def cell_size(self) -> int:
        return max(2, round(self.BASE_CELL_SIZE * self.zoom_percent / 100))

    def set_pattern(self, session: PatternEditSession | None, palette: Palette | None) -> None:
        self._cancel_active_stroke()
        self.session = session
        self.palette = palette
        self._hovered_cell = None
        self._resize_to_pattern()
        self.update()

    def set_tool(self, tool: EditTool) -> None:
        self.tool = tool
        self.setCursor(Qt.CrossCursor if tool is not EditTool.PICKER else Qt.PointingHandCursor)

    def set_selected_color(self, code: str | None) -> None:
        self.selected_color = code

    def set_interaction_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled and self.session is not None)
        if self.interaction_enabled and not enabled:
            self._cancel_active_stroke()
        self.interaction_enabled = enabled
        self.setFocusPolicy(Qt.StrongFocus if enabled else Qt.NoFocus)
        self.update()

    def set_zoom(self, value: int) -> None:
        value = max(10, min(800, int(value)))
        if value == self.zoom_percent:
            return
        self.zoom_percent = value
        self._resize_to_pattern()
        self.update()

    def set_display_options(self, *, show_grid: bool, show_codes: bool) -> None:
        self.show_grid = show_grid
        self.show_codes = show_codes
        self.update()

    def cell_at_point(self, point: QPoint) -> tuple[int, int] | None:
        if self.session is None or point.x() < 0 or point.y() < 0:
            return None
        column = point.x() // self.cell_size
        row = point.y() // self.cell_size
        if row >= self.session.height or column >= self.session.width:
            return None
        return row, column

    def sizeHint(self) -> QSize:
        if self.session is None:
            return QSize(520, 420)
        return QSize(
            self.session.width * self.cell_size,
            self.session.height * self.cell_size,
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(event.rect(), QColor("#F8FAFC"))
        if self.session is None or self.palette is None:
            painter.setPen(QColor("#6B7280"))
            painter.drawText(self.rect(), Qt.AlignCenter, "调整参数后生成图纸")
            return

        cell_size = self.cell_size
        exposed = event.rect()
        first_column = max(0, exposed.left() // cell_size)
        last_column = min(self.session.width - 1, exposed.right() // cell_size)
        first_row = max(0, exposed.top() // cell_size)
        last_row = min(self.session.height - 1, exposed.bottom() // cell_size)
        color_map = {color.code.casefold(): color for color in self.palette.colors}
        margin = max(1, cell_size // 12)
        font = QFont(self.font())
        font.setPixelSize(max(8, min(18, cell_size // 3)))
        painter.setFont(font)

        for row in range(first_row, last_row + 1):
            for column in range(first_column, last_column + 1):
                palette_index = self.session.cells[row][column]
                if palette_index < 0:
                    continue
                code = self.session.palette_codes[palette_index]
                color = color_map.get(code.casefold())
                if color is None:
                    continue
                bounds = QRect(
                    column * cell_size + margin,
                    row * cell_size + margin,
                    max(1, cell_size - margin * 2),
                    max(1, cell_size - margin * 2),
                )
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color.hex))
                painter.drawEllipse(bounds)
                if self.show_codes and cell_size >= 18:
                    red, green, blue = color.rgb
                    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                    painter.setPen(QColor("#111111" if luminance > 145 else "#FFFFFF"))
                    painter.drawText(bounds, Qt.AlignCenter, code)

        if self.show_grid:
            painter.setRenderHint(QPainter.Antialiasing, False)
            painter.setPen(QPen(QColor("#D2D7DE"), 1))
            start_x = first_column * cell_size
            end_x = min(self.width() - 1, (last_column + 1) * cell_size)
            start_y = first_row * cell_size
            end_y = min(self.height() - 1, (last_row + 1) * cell_size)
            for column in range(first_column, last_column + 2):
                x = min(self.width() - 1, column * cell_size)
                painter.drawLine(x, start_y, x, end_y)
            for row in range(first_row, last_row + 2):
                y = min(self.height() - 1, row * cell_size)
                painter.drawLine(start_x, y, end_x, y)

        if self._hovered_cell is not None:
            row, column = self._hovered_cell
            highlight = QRect(column * cell_size, row * cell_size, cell_size, cell_size)
            painter.setBrush(QColor(24, 90, 189, 38))
            painter.setPen(QPen(QColor("#185ABD"), 2))
            painter.drawRect(highlight.adjusted(1, 1, -1, -1))

        if not self.interaction_enabled:
            painter.fillRect(event.rect(), QColor(255, 255, 255, 28))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.LeftButton or not self.interaction_enabled or self.session is None:
            super().mousePressEvent(event)
            return
        cell = self.cell_at_point(event.position().toPoint())
        if cell is None:
            return
        self.setFocus(Qt.MouseFocusReason)
        row, column = cell
        if self.tool is EditTool.PICKER:
            code = self.session.pick_code(row, column)
            self.color_picked.emit(code or "")
            return
        if self.tool is EditTool.BRUSH and not self.selected_color:
            return
        self.session.begin_stroke(self.tool)
        self._stroke_active = True
        self._last_stroke_cell = cell
        if self.session.apply_cell(row, column, self.selected_color):
            self._update_cell(row, column)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        cell = self.cell_at_point(event.position().toPoint())
        if cell != self._hovered_cell:
            previous = self._hovered_cell
            self._hovered_cell = cell
            if previous is not None:
                self._update_cell(*previous)
            if cell is not None:
                self._update_cell(*cell)
                self.coordinate_hovered.emit(*cell)
            else:
                self.coordinate_hovered.emit(-1, -1)
        if not self._stroke_active or self.session is None or cell is None:
            return
        if not (event.buttons() & Qt.LeftButton) or self._last_stroke_cell is None:
            return
        start_row, start_column = self._last_stroke_cell
        end_row, end_column = cell
        if self.session.apply_line(
            start_row,
            start_column,
            end_row,
            end_column,
            self.selected_color,
        ):
            self.update(self._line_update_rect(start_row, start_column, end_row, end_column))
        self._last_stroke_cell = cell

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self._stroke_active and self.session is not None:
            command = self.session.end_stroke()
            self._stroke_active = False
            self._last_stroke_cell = None
            if command is not None:
                self.stroke_committed.emit()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        previous = self._hovered_cell
        self._hovered_cell = None
        if previous is not None:
            self._update_cell(*previous)
        self.coordinate_hovered.emit(-1, -1)
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.ControlModifier:
            steps = math.copysign(10, event.angleDelta().y()) if event.angleDelta().y() else 0
            if steps:
                self.zoom_requested.emit(self.zoom_percent + int(steps))
                event.accept()
                return
        event.ignore()

    def _resize_to_pattern(self) -> None:
        hint = self.sizeHint()
        self.setMinimumSize(hint)
        self.setMaximumSize(hint)
        self.resize(hint)
        self.updateGeometry()

    def _update_cell(self, row: int, column: int) -> None:
        cell_size = self.cell_size
        self.update(column * cell_size, row * cell_size, cell_size + 1, cell_size + 1)

    def _line_update_rect(
        self,
        start_row: int,
        start_column: int,
        end_row: int,
        end_column: int,
    ) -> QRect:
        cell_size = self.cell_size
        left = min(start_column, end_column) * cell_size
        top = min(start_row, end_row) * cell_size
        width = (abs(end_column - start_column) + 1) * cell_size + 1
        height = (abs(end_row - start_row) + 1) * cell_size + 1
        return QRect(left, top, width, height)

    def _cancel_active_stroke(self) -> None:
        if self._stroke_active and self.session is not None:
            self.session.cancel_stroke()
        self._stroke_active = False
        self._last_stroke_cell = None
