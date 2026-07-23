from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from perler_pattern.domain.models import SourceImage


MAX_SOURCE_BYTES = 256 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


class ImageImportError(ValueError):
    pass


def decode_source(source: SourceImage) -> Image.Image:
    try:
        with Image.open(io.BytesIO(source.data)) as opened:
            normalized = ImageOps.exif_transpose(opened)
            normalized.load()
            return normalized.convert("RGBA")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageImportError(f"无法解码图片：{error}") from error


def import_source(path: str | Path) -> SourceImage:
    image_path = Path(path)
    extension = image_path.suffix.casefold()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ImageImportError("仅支持 PNG、JPEG、WebP 和 BMP 图片")
    try:
        size = image_path.stat().st_size
        if size < 1 or size > MAX_SOURCE_BYTES:
            raise ImageImportError("图片为空或超过 256 MiB")
        data = image_path.read_bytes()
        with Image.open(io.BytesIO(data)) as opened:
            image_format = opened.format
            normalized = ImageOps.exif_transpose(opened)
            normalized.load()
            width, height = normalized.size
    except ImageImportError:
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ImageImportError(f"无法导入图片：{error}") from error
    media_type = Image.MIME.get(image_format or "", f"image/{extension.removeprefix('.')}")
    return SourceImage(
        data=data,
        original_name=image_path.name,
        media_type=media_type,
        width=width,
        height=height,
        extension=extension,
        exif_orientation_applied=True,
    )
