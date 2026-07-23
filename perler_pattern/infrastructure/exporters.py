from __future__ import annotations

import csv
import io
import math
import os
import re
import uuid
from html import escape
from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen, QPixmap

from perler_pattern.domain.models import Project
from perler_pattern.processing.render import render_pattern_png


class ExportError(ValueError):
    pass


def export_project(project: Project, format_id: str, path: Path) -> Path:
    if project.grid is None:
        raise ExportError("工程尚未生成图纸")
    normalized = format_id.casefold()
    target = path if path.suffix.casefold() == f".{normalized}" else path.with_suffix(f".{normalized}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        if normalized == "png":
            _export_png(project, temporary)
        elif normalized == "svg":
            _export_svg(project, temporary)
        elif normalized == "pdf":
            _export_pdf(project, temporary)
        elif normalized == "csv":
            _export_csv(project, temporary)
        else:
            raise ExportError(f"不支持的导出格式：{format_id}")
        if not temporary.exists() or temporary.stat().st_size == 0:
            raise ExportError("导出器未生成有效文件")
        os.replace(temporary, target)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    return target


def _export_png(project: Project, path: Path) -> None:
    options = project.export_settings.get("png", {})
    scale = int(options.get("scale", 4))
    if not 1 <= scale <= 16:
        raise ExportError("PNG 缩放必须在 1..16")
    cell_size = scale * 8
    if project.grid.width * cell_size > 32767 or project.grid.height * cell_size > 32767:
        raise ExportError("PNG 任一边不得超过 32767 像素")
    background_value = options.get("background", "#FFFFFF")
    background = None if background_value in {None, "transparent"} else str(background_value)
    data = render_pattern_png(
        project.grid,
        project.palette,
        cell_size=cell_size,
        show_grid=bool(options.get("show_grid", True)),
        show_codes=bool(options.get("show_codes", True)),
        background=background,
    )
    path.write_bytes(data)


def _export_svg(project: Project, path: Path) -> None:
    options = project.export_settings.get("svg", {})
    show_grid = bool(options.get("show_grid", True))
    show_codes = bool(options.get("show_codes", True))
    include_legend = bool(options.get("include_legend", True))
    cell = 28
    legend_width = 250 if include_legend else 0
    width = project.grid.width * cell + legend_width
    height = max(project.grid.height * cell, 60 + len(project.usage_summary().items) * 24 if include_legend else 0)
    color_map = {color.code: color for color in project.palette.colors}
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g id="pattern">',
    ]
    for row_index, row in enumerate(project.grid.cells):
        for column_index, palette_index in enumerate(row):
            x = column_index * cell
            y = row_index * cell
            if palette_index >= 0:
                code = project.grid.palette_codes[palette_index]
                color = color_map[code]
                parts.append(f'<circle cx="{x + cell / 2:.3f}" cy="{y + cell / 2:.3f}" r="{cell * 0.42:.3f}" fill="{color.hex}"/>')
                if show_codes:
                    luminance = sum(color.rgb)
                    text_color = "#111111" if luminance > 400 else "#FFFFFF"
                    parts.append(f'<text x="{x + cell / 2:.3f}" y="{y + cell * 0.62:.3f}" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="8" fill="{text_color}">{escape(code)}</text>')
            if show_grid:
                parts.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" fill="none" stroke="#C8CCD0" stroke-width="0.7"/>')
    parts.append("</g>")
    if include_legend:
        legend_x = project.grid.width * cell + 24
        parts.append(f'<g id="legend"><text x="{legend_x}" y="28" font-size="16" font-family="Microsoft YaHei UI, sans-serif">用珠图例</text>')
        for index, item in enumerate(project.usage_summary().items):
            y = 52 + index * 24
            parts.append(f'<circle cx="{legend_x + 8}" cy="{y - 5}" r="7" fill="{item.hex}"/>')
            parts.append(f'<text x="{legend_x + 24}" y="{y}" font-size="11" font-family="Microsoft YaHei UI, sans-serif">{escape(item.code)} {escape(item.name)} × {item.quantity}</text>')
        parts.append("</g>")
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8", newline="\n")


def _export_csv(project: Project, path: Path) -> None:
    def natural_key(text: str) -> list[object]:
        return [int(value) if value.isdigit() else value.casefold() for value in re.split(r"(\d+)", text)]

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(["色号", "名称", "颜色值", "数量", "库存", "缺口"])
    for item in sorted(project.usage_summary().items, key=lambda value: natural_key(value.code)):
        writer.writerow(
            [
                item.code,
                item.name,
                item.hex,
                item.quantity,
                "" if item.stock is None else item.stock,
                "" if item.shortage is None else item.shortage,
            ]
        )
    path.write_bytes(b"\xef\xbb\xbf" + output.getvalue().encode("utf-8"))


def _export_pdf(project: Project, path: Path) -> None:
    writer = QPdfWriter(str(path))
    writer.setResolution(144)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
    writer.setTitle(project.metadata.title)
    writer.setCreator("拼豆图纸生成器 2.0")
    painter = QPainter(writer)
    if not painter.isActive():
        raise ExportError("无法创建 PDF")
    try:
        page = writer.pageLayout().paintRectPixels(writer.resolution())
        _paint_pdf_overview(painter, QRectF(page), project)
        page_width, page_height, columns, rows = pdf_tile_layout(project)
        for board_row in range(rows):
            for board_column in range(columns):
                writer.newPage()
                _paint_pdf_board(
                    painter,
                    QRectF(page),
                    project,
                    board_column,
                    board_row,
                    page_width,
                    page_height,
                )
        writer.newPage()
        _paint_pdf_legend(painter, QRectF(page), project)
    finally:
        painter.end()


def _paint_heading(painter: QPainter, page: QRectF, text: str, subtitle: str = "") -> float:
    painter.setPen(QColor("#242424"))
    painter.setFont(QFont("Microsoft YaHei UI", 20, QFont.Bold))
    painter.drawText(QRectF(page.left(), page.top(), page.width(), 55), Qt.AlignLeft | Qt.AlignVCenter, text)
    if subtitle:
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor("#666666"))
        painter.drawText(QRectF(page.left(), page.top() + 44, page.width(), 32), Qt.AlignLeft | Qt.AlignVCenter, subtitle)
    return page.top() + 82


def pdf_tile_layout(project: Project) -> tuple[int, int, int, int]:
    if project.grid is None:
        raise ExportError("工程尚未生成图纸")
    page_width = min(project.boards.width, 16)
    page_height = min(project.boards.height, 16)
    columns = math.ceil(project.grid.width / page_width)
    rows = math.ceil(project.grid.height / page_height)
    return page_width, page_height, columns, rows


def pdf_tile_bounds(project: Project) -> tuple[tuple[int, int, int, int], ...]:
    page_width, page_height, columns, rows = pdf_tile_layout(project)
    return tuple(
        (
            column * page_width,
            row * page_height,
            min((column + 1) * page_width, project.grid.width),
            min((row + 1) * page_height, project.grid.height),
        )
        for row in range(rows)
        for column in range(columns)
    )


def _paint_pdf_overview(painter: QPainter, page: QRectF, project: Project) -> None:
    usage = project.usage_summary()
    top = _paint_heading(painter, page, project.metadata.title, f"作者：{project.metadata.author or '未填写'}  ·  {project.grid.width}×{project.grid.height}  ·  总珠数 {usage.total_beads}")
    preview = QPixmap()
    preview.loadFromData(render_pattern_png(project.grid, project.palette, cell_size=16, show_grid=True, show_codes=False))
    area = QRectF(page.left(), top, page.width(), page.height() - top - 70)
    scaled = preview.scaled(int(area.width()), int(area.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter.drawPixmap(int(area.center().x() - scaled.width() / 2), int(area.top()), scaled)
    painter.setFont(QFont("Microsoft YaHei UI", 9))
    painter.setPen(QColor("#444444"))
    painter.drawText(QRectF(page.left(), page.bottom() - 55, page.width(), 50), Qt.TextWordWrap, project.metadata.notes or "无备注")


def _paint_pdf_board(
    painter: QPainter,
    page: QRectF,
    project: Project,
    board_column: int,
    board_row: int,
    page_width: int,
    page_height: int,
) -> None:
    start_x = board_column * page_width
    start_y = board_row * page_height
    end_x = min(start_x + page_width, project.grid.width)
    end_y = min(start_y + page_height, project.grid.height)
    top = _paint_heading(painter, page, f"制作页：分块 {board_column + 1},{board_row + 1}", f"单页不超过 16×16 · 全局范围 X {start_x + 1}–{end_x} · Y {start_y + 1}–{end_y}")
    width = end_x - start_x
    height = end_y - start_y
    cell = min((page.width() - 50) / width, (page.height() - top - 110) / height)
    origin_x = page.left() + (page.width() - width * cell) / 2
    origin_y = top + 30
    color_map = {color.code: color for color in project.palette.colors}
    painter.setFont(QFont("Segoe UI", max(5, int(cell / 5))))
    used: set[str] = set()
    for local_y, global_y in enumerate(range(start_y, end_y)):
        for local_x, global_x in enumerate(range(start_x, end_x)):
            palette_index = project.grid.cells[global_y][global_x]
            rect = QRectF(origin_x + local_x * cell, origin_y + local_y * cell, cell, cell)
            if palette_index >= 0:
                code = project.grid.palette_codes[palette_index]
                color = color_map[code]
                used.add(code)
                painter.setBrush(QColor(color.hex))
                painter.setPen(Qt.NoPen)
                margin = max(1.0, cell * 0.08)
                painter.drawEllipse(rect.adjusted(margin, margin, -margin, -margin))
                painter.setPen(QColor("#111111" if sum(color.rgb) > 400 else "#FFFFFF"))
                painter.drawText(rect, Qt.AlignCenter, code)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor("#AAB0B5"), 0.6))
            painter.drawRect(rect)
    painter.setPen(QColor("#444444"))
    painter.setFont(QFont("Microsoft YaHei UI", 8))
    legend = "本页颜色：" + "  ".join(sorted(used))
    painter.drawText(QRectF(page.left(), page.bottom() - 55, page.width(), 50), Qt.TextWordWrap, legend)


def _paint_pdf_legend(painter: QPainter, page: QRectF, project: Project) -> None:
    top = _paint_heading(painter, page, "全局用珠图例", f"总珠数 {project.usage_summary().total_beads}")
    painter.setFont(QFont("Microsoft YaHei UI", 10))
    row_height = 34
    columns = 2
    column_width = page.width() / columns
    for index, item in enumerate(project.usage_summary().items):
        column = index % columns
        row = index // columns
        x = page.left() + column * column_width
        y = top + row * row_height
        painter.setBrush(QColor(item.hex))
        painter.setPen(QPen(QColor("#666666"), 0.5))
        painter.drawEllipse(QRectF(x, y + 4, 22, 22))
        painter.setPen(QColor("#242424"))
        stock = "未设置库存" if item.stock is None else f"库存 {item.stock} / 缺口 {item.shortage}"
        painter.drawText(QRectF(x + 32, y, column_width - 38, row_height), Qt.AlignVCenter, f"{item.code} {item.name}  × {item.quantity}  {stock}")
