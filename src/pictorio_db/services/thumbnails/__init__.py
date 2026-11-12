# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Thumbnails for the desktop app's grid and image view: WebP, upright, by SHA-256."""

import os
from pathlib import Path

from PIL import Image, ImageOps

from pictorio_db.utils import image_limits  # noqa: F401  (allows the large JPEGs the importer accepts)
from pictorio_db.utils.problems import Problem

THUMBNAIL_SIZES = (256, 1024)  # longest side in pixels
WEBP_QUALITY = 80

# Modes WebP can store as they are; others (CMYK, 16-bit, palette...) are converted first.
_WEBP_MODES = {"RGB", "RGBA"}


class ThumbnailsService:
    def __init__(self, thumbnails_dir: Path) -> None:
        self._thumbnails_dir = thumbnails_dir

    def thumbnail_path(self, sha256: str, size: int) -> Path:
        """thumbnails/<size>/<first two hex digits>/<sha256>.webp: no folder gets too many files."""
        if size not in THUMBNAIL_SIZES:
            raise ValueError(f"Thumbnail sizes are {THUMBNAIL_SIZES}, not {size}")

        return self._thumbnails_dir / str(size) / sha256[:2] / f"{sha256}.webp"

    def create_thumbnails(self, image_path: Path, sha256: str) -> None:
        """Decodes the whole image, so damaged image data is found here: raises 415."""
        largest = _upright_image_fitting(image_path, max(THUMBNAIL_SIZES))
        for size in sorted(THUMBNAIL_SIZES, reverse=True):
            largest.thumbnail((size, size))  # each smaller size from the previous one, not the original
            _save_atomically(largest, self.thumbnail_path(sha256, size))

    def delete_thumbnails(self, sha256: str) -> None:
        for size in THUMBNAIL_SIZES:
            self.thumbnail_path(sha256, size).unlink(missing_ok=True)


def _upright_image_fitting(image_path: Path, size: int) -> Image.Image:
    try:
        with Image.open(image_path) as image:
            image.draft("RGB", (size, size))  # JPEG decodes straight at a reduced size: much faster
            upright = ImageOps.exif_transpose(image)  # also reads the whole image (first frame if animated)
            upright.thumbnail((size, size))
            return upright if upright.mode in _WEBP_MODES else upright.convert(_webp_mode(upright))
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise Problem(
            415, "unsupported_media_type", "Not a supported image", "The image data is damaged."
        ) from None


def _webp_mode(image: Image.Image) -> str:
    has_transparency = "A" in image.getbands() or "transparency" in image.info
    return "RGBA" if has_transparency else "RGB"


def _save_atomically(image: Image.Image, path: Path) -> None:
    """Written under another name first, so a crash never leaves half a thumbnail."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    image.save(partial, format="WEBP", quality=WEBP_QUALITY)
    os.replace(partial, path)


__all__ = ["THUMBNAIL_SIZES", "ThumbnailsService"]
