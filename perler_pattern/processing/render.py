from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from perler_pattern.domain.models import Palette, PatternGrid


def render_pattern_png(
    grid: PatternGrid,
    palette: Palette,
    *,
    cell_size: int = 24,
    show_grid: bool = True,
    show_codes: bool = True,
    background: str | None = "#FFFFFF",
    round_beads: bool = True,
) -> bytes:
    if not 1 <= cell_size <= 256:
        raise ValueError("Cell size must be between 1 and 256")
    mode = "RGBA"
    fill = (0, 0, 0, 0) if background is None else background
    image = Image.new(mode, (grid.width * cell_size, grid.height * cell_size), fill)
    draw = ImageDraw.Draw(image)
    color_map = {color.code: color for color in palette.colors}
    font = ImageFont.load_default(size=max(8, min(18, cell_size // 3)))
    margin = max(1, cell_size // 12)
    for row_index, row in enumerate(grid.cells):
        for column_index, palette_index in enumerate(row):
            if palette_index < 0:
                continue
            color = color_map[grid.palette_codes[palette_index]]
            left = column_index * cell_size
            top = row_index * cell_size
            bounds = (left + margin, top + margin, left + cell_size - margin - 1, top + cell_size - margin - 1)
            if round_beads:
                draw.ellipse(bounds, fill=color.hex)
            else:
                draw.rectangle(bounds, fill=color.hex)
            if show_codes and cell_size >= 16:
                luminance = 0.2126 * color.rgb[0] + 0.7152 * color.rgb[1] + 0.0722 * color.rgb[2]
                text_color = "#111111" if luminance > 145 else "#FFFFFF"
                text = color.code
                box = draw.textbbox((0, 0), text, font=font)
                draw.text(
                    (left + (cell_size - (box[2] - box[0])) / 2, top + (cell_size - (box[3] - box[1])) / 2),
                    text,
                    fill=text_color,
                    font=font,
                )
    if show_grid:
        line_color = "#C8CCD0"
        for column in range(grid.width + 1):
            x = min(column * cell_size, image.width - 1)
            draw.line((x, 0, x, image.height), fill=line_color, width=1)
        for row in range(grid.height + 1):
            y = min(row * cell_size, image.height - 1)
            draw.line((0, y, image.width, y), fill=line_color, width=1)
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    return output.getvalue()


def render_preview_png(grid: PatternGrid, palette: Palette) -> bytes:
    cell_size = max(4, min(24, 2048 // max(grid.width, grid.height)))
    return render_pattern_png(grid, palette, cell_size=cell_size, show_grid=True, show_codes=cell_size >= 18)
