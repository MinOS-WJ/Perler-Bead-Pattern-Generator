from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from threading import Event

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from perler_pattern.domain.models import (
    Dithering,
    FitMode,
    GenerationSettings,
    Palette,
    PatternGrid,
    SourceImage,
    utc_now,
)
from perler_pattern.processing.color import nearest_palette_indices, srgb_to_lab
from perler_pattern.processing.image_io import decode_source


ProgressCallback = Callable[[int, str], None]


class GenerationCancelled(RuntimeError):
    pass


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled("生成已取消")


def _progress(callback: ProgressCallback | None, value: int, text: str) -> None:
    if callback is not None:
        callback(value, text)


def _transform_image(image: Image.Image, settings: GenerationSettings) -> Image.Image:
    if settings.rotation:
        image = image.rotate(-settings.rotation, expand=True)
    if settings.flip_horizontal:
        image = ImageOps.mirror(image)
    if settings.flip_vertical:
        image = ImageOps.flip(image)
    if settings.brightness != 1:
        image = ImageEnhance.Brightness(image).enhance(settings.brightness)
    if settings.contrast != 1:
        image = ImageEnhance.Contrast(image).enhance(settings.contrast)
    if settings.saturation != 1:
        image = ImageEnhance.Color(image).enhance(settings.saturation)
    if settings.sharpness != 1:
        image = ImageEnhance.Sharpness(image).enhance(settings.sharpness)
    return image


def _fit_image(image: Image.Image, settings: GenerationSettings) -> Image.Image:
    target = (settings.grid_width, settings.grid_height)
    if settings.fit_mode is FitMode.STRETCH:
        return image.resize(target, Image.Resampling.LANCZOS)
    if settings.fit_mode is FitMode.FILL_CROP:
        return ImageOps.fit(image, target, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    contained = image.copy()
    contained.thumbnail(target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", target, (0, 0, 0, 0))
    offset = ((target[0] - contained.width) // 2, (target[1] - contained.height) // 2)
    canvas.alpha_composite(contained, offset)
    return canvas


def _select_colors(rgb: np.ndarray, palette: Palette, maximum: int) -> tuple[list, np.ndarray]:
    enabled = palette.enabled_colors
    palette_rgb = np.asarray([color.rgb for color in enabled], dtype=np.float64)
    palette_lab = srgb_to_lab(palette_rgb)
    if len(enabled) <= maximum:
        return enabled, palette_lab
    assignments = nearest_palette_indices(rgb, palette_lab)
    counts = np.bincount(assignments, minlength=len(enabled))
    selected_indices = np.argsort(-counts, kind="stable")[:maximum]
    return [enabled[index] for index in selected_indices], palette_lab[selected_indices]


def _floyd_steinberg(
    rgb: np.ndarray,
    visible: np.ndarray,
    palette_rgb: np.ndarray,
    palette_lab: np.ndarray,
    strength: float,
    cancel_event: Event | None,
) -> np.ndarray:
    working = rgb.astype(np.float64).copy()
    height, width, _ = working.shape
    result = np.full((height, width), -1, dtype=np.int32)
    processed = 0
    for row in range(height):
        for column in range(width):
            if not visible[row, column]:
                continue
            current = np.clip(working[row, column], 0, 255)
            index = int(nearest_palette_indices(current[None, :], palette_lab)[0])
            result[row, column] = index
            error = (current - palette_rgb[index]) * strength
            for row_offset, column_offset, weight in (
                (0, 1, 7 / 16),
                (1, -1, 3 / 16),
                (1, 0, 5 / 16),
                (1, 1, 1 / 16),
            ):
                target_row = row + row_offset
                target_column = column + column_offset
                if (
                    target_row < height
                    and 0 <= target_column < width
                    and visible[target_row, target_column]
                ):
                    working[target_row, target_column] += error * weight
            processed += 1
            if processed % 1024 == 0:
                _check_cancel(cancel_event)
    return result


def _despeckle(cells: np.ndarray, iterations: int, cancel_event: Event | None) -> np.ndarray:
    result = cells.copy()
    height, width = result.shape
    for _iteration in range(iterations):
        source = result.copy()
        for row in range(height):
            for column in range(width):
                current = source[row, column]
                if current < 0:
                    continue
                neighbors = source[
                    max(0, row - 1) : min(height, row + 2),
                    max(0, column - 1) : min(width, column + 2),
                ].ravel()
                neighbors = neighbors[neighbors >= 0]
                if len(neighbors) < 5:
                    continue
                values, counts = np.unique(neighbors, return_counts=True)
                replacement = int(values[np.argmax(counts)])
                if replacement != current and int(np.max(counts)) >= 5:
                    result[row, column] = replacement
        _check_cancel(cancel_event)
    return result


def generate_pattern(
    source: SourceImage,
    settings: GenerationSettings,
    palette: Palette,
    *,
    input_fingerprint: str,
    cancel_event: Event | None = None,
    progress: ProgressCallback | None = None,
) -> PatternGrid:
    settings = replace(settings)
    _check_cancel(cancel_event)
    _progress(progress, 5, "正在解码图片")
    image = decode_source(source)
    image = _transform_image(image, settings)
    _check_cancel(cancel_event)
    _progress(progress, 20, "正在调整图片")
    image = _fit_image(image, settings)
    rgba = np.asarray(image, dtype=np.uint8)
    visible = rgba[..., 3] >= settings.alpha_threshold
    visible_rgb = rgba[..., :3][visible]
    if len(visible_rgb) == 0:
        cells = np.full((settings.grid_height, settings.grid_width), -1, dtype=np.int32)
        return PatternGrid(
            settings.grid_width,
            settings.grid_height,
            (),
            tuple(tuple(int(value) for value in row) for row in cells),
            utc_now(),
            input_fingerprint,
        )
    _check_cancel(cancel_event)
    _progress(progress, 40, "正在选择代表颜色")
    selected, selected_lab = _select_colors(visible_rgb, palette, min(settings.max_colors, len(palette.enabled_colors)))
    palette_rgb = np.asarray([color.rgb for color in selected], dtype=np.float64)
    if settings.dithering is Dithering.FLOYD_STEINBERG:
        cells = _floyd_steinberg(
            rgba[..., :3],
            visible,
            palette_rgb,
            selected_lab,
            settings.dither_strength,
            cancel_event,
        )
    else:
        cells = np.full(visible.shape, -1, dtype=np.int32)
        cells[visible] = nearest_palette_indices(visible_rgb, selected_lab)
    _check_cancel(cancel_event)
    _progress(progress, 80, "正在简化孤点")
    cells = _despeckle(cells, settings.despeckle_iterations, cancel_event)
    _progress(progress, 100, "图纸生成完成")
    return PatternGrid(
        settings.grid_width,
        settings.grid_height,
        tuple(color.code for color in selected),
        tuple(tuple(int(value) for value in row) for row in cells),
        utc_now(),
        input_fingerprint,
    )
