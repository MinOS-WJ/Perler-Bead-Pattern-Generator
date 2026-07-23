from __future__ import annotations

import numpy as np


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    values = np.asarray(rgb, dtype=np.float64) / 255.0
    linear = np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )
    matrix = np.array(
        [
            [0.4124564, 0.3575761, 0.1804375],
            [0.2126729, 0.7151522, 0.0721750],
            [0.0193339, 0.1191920, 0.9503041],
        ]
    )
    xyz = linear @ matrix.T
    reference = np.array([0.95047, 1.0, 1.08883])
    scaled = xyz / reference
    delta = 6 / 29
    transformed = np.where(
        scaled > delta**3,
        np.cbrt(scaled),
        scaled / (3 * delta**2) + 4 / 29,
    )
    lightness = 116 * transformed[..., 1] - 16
    a_value = 500 * (transformed[..., 0] - transformed[..., 1])
    b_value = 200 * (transformed[..., 1] - transformed[..., 2])
    return np.stack((lightness, a_value, b_value), axis=-1)


def ciede2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = np.moveaxis(first, -1, 0)
    l2, a2, b2 = np.moveaxis(second, -1, 0)
    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    mean_c = (c1 + c2) / 2
    correction = 0.5 * (1 - np.sqrt(mean_c**7 / (mean_c**7 + 25**7)))
    adjusted_a1 = (1 + correction) * a1
    adjusted_a2 = (1 + correction) * a2
    adjusted_c1 = np.hypot(adjusted_a1, b1)
    adjusted_c2 = np.hypot(adjusted_a2, b2)
    hue1 = np.mod(np.degrees(np.arctan2(b1, adjusted_a1)), 360)
    hue2 = np.mod(np.degrees(np.arctan2(b2, adjusted_a2)), 360)

    delta_l = l2 - l1
    delta_c = adjusted_c2 - adjusted_c1
    hue_difference = hue2 - hue1
    hue_difference = np.where(hue_difference > 180, hue_difference - 360, hue_difference)
    hue_difference = np.where(hue_difference < -180, hue_difference + 360, hue_difference)
    hue_difference = np.where((adjusted_c1 * adjusted_c2) == 0, 0, hue_difference)
    delta_h = 2 * np.sqrt(adjusted_c1 * adjusted_c2) * np.sin(np.radians(hue_difference / 2))

    mean_l = (l1 + l2) / 2
    mean_adjusted_c = (adjusted_c1 + adjusted_c2) / 2
    hue_sum = hue1 + hue2
    mean_hue = np.where(
        (adjusted_c1 * adjusted_c2) == 0,
        hue_sum,
        np.where(
            np.abs(hue1 - hue2) <= 180,
            hue_sum / 2,
            np.where(hue_sum < 360, (hue_sum + 360) / 2, (hue_sum - 360) / 2),
        ),
    )
    weighting = (
        1
        - 0.17 * np.cos(np.radians(mean_hue - 30))
        + 0.24 * np.cos(np.radians(2 * mean_hue))
        + 0.32 * np.cos(np.radians(3 * mean_hue + 6))
        - 0.20 * np.cos(np.radians(4 * mean_hue - 63))
    )
    rotation_delta = 30 * np.exp(-((mean_hue - 275) / 25) ** 2)
    chroma_factor = 2 * np.sqrt(mean_adjusted_c**7 / (mean_adjusted_c**7 + 25**7))
    lightness_scale = 1 + 0.015 * (mean_l - 50) ** 2 / np.sqrt(20 + (mean_l - 50) ** 2)
    chroma_scale = 1 + 0.045 * mean_adjusted_c
    hue_scale = 1 + 0.015 * mean_adjusted_c * weighting
    rotation = -np.sin(np.radians(2 * rotation_delta)) * chroma_factor
    lightness_term = delta_l / lightness_scale
    chroma_term = delta_c / chroma_scale
    hue_term = delta_h / hue_scale
    return np.sqrt(
        lightness_term**2
        + chroma_term**2
        + hue_term**2
        + rotation * chroma_term * hue_term
    )


def nearest_palette_indices(
    rgb: np.ndarray,
    palette_lab: np.ndarray,
    *,
    chunk_size: int = 4096,
) -> np.ndarray:
    pixels = np.asarray(rgb, dtype=np.float64).reshape(-1, 3)
    result = np.empty(len(pixels), dtype=np.int32)
    for start in range(0, len(pixels), chunk_size):
        stop = min(start + chunk_size, len(pixels))
        labs = srgb_to_lab(pixels[start:stop])
        distances = ciede2000(labs[:, None, :], palette_lab[None, :, :])
        result[start:stop] = np.argmin(distances, axis=1)
    return result
