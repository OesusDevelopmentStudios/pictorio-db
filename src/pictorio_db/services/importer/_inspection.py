# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What an uploaded file is: its type from the content (never the name), its size as shown, when it was
taken, and its SHA-256."""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, UnidentifiedImageError

from pictorio_db.utils.problems import Problem


@dataclass(frozen=True)
class ImageType:
    mime_type: str
    extension: str  # used for the file name in the library


# Pillow's format name → type. MPO is how Pillow reports many camera JPEGs (JPEG with extra pictures).
SUPPORTED_TYPES = {
    "JPEG": ImageType("image/jpeg", "jpg"),
    "MPO": ImageType("image/jpeg", "jpg"),
    "PNG": ImageType("image/png", "png"),
    "WEBP": ImageType("image/webp", "webp"),
    "GIF": ImageType("image/gif", "gif"),
    "TIFF": ImageType("image/tiff", "tiff"),
    "BMP": ImageType("image/bmp", "bmp"),
    "JPEG2000": ImageType("image/jp2", "jp2"),
    "AVIF": ImageType("image/avif", "avif"),
}

# EXIF orientations that turn the picture by 90° or 270°, so width and height swap when it is shown
_SIDEWAYS_ORIENTATIONS = {5, 6, 7, 8}
_EXIF_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"
_HASH_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ImageFacts:
    type: ImageType
    width: int  # as the image is shown, i.e. after the EXIF orientation
    height: int
    taken_at: datetime | None  # local wall-clock time from EXIF; None if the file does not say
    taken_at_utc_offset_minutes: int | None


def inspect_image(path: Path) -> ImageFacts:
    """Raises 415 unsupported_media_type for files that are not a supported image."""
    try:
        with Image.open(path) as image:
            image_type = SUPPORTED_TYPES.get(image.format or "")
            if image_type is None:
                raise _unsupported(Image.MIME.get(image.format or ""))

            exif = image.getexif()
            width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise _unsupported(None) from None

    if exif.get(ExifTags.Base.Orientation) in _SIDEWAYS_ORIENTATIONS:
        width, height = height, width

    taken_at, utc_offset_minutes = _capture_time(exif)
    return ImageFacts(image_type, width, height, taken_at, utc_offset_minutes)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)

    return digest.hexdigest()


def _capture_time(exif: Image.Exif) -> tuple[datetime | None, int | None]:
    """DateTimeOriginal, else DateTimeDigitized, like the desktop app. The UTC offset is known only for
    DateTimeOriginal."""
    photo_tags = exif.get_ifd(ExifTags.IFD.Exif)
    original = _parse_exif_date(photo_tags.get(ExifTags.Base.DateTimeOriginal))
    if original is not None:
        return original, _parse_utc_offset(photo_tags.get(ExifTags.Base.OffsetTimeOriginal))

    return _parse_exif_date(photo_tags.get(ExifTags.Base.DateTimeDigitized)), None


def _parse_exif_date(value: object) -> datetime | None:
    """None for missing or unset dates; cameras without a set clock write '0000:00:00 00:00:00'."""
    if not isinstance(value, str):
        return None

    try:
        return datetime.strptime(value.strip().rstrip("\x00"), _EXIF_DATE_FORMAT)
    except ValueError:
        return None


def _parse_utc_offset(value: object) -> int | None:
    """'+02:00' → 120, '-05:30' → -330."""
    if not isinstance(value, str) or len(value.strip()) != 6:
        return None

    text = value.strip()
    sign = {"+": 1, "-": -1}.get(text[0])
    hours, separator, minutes = text[1:3], text[3], text[4:6]
    if sign is None or separator != ":" or not (hours.isdigit() and minutes.isdigit()):
        return None

    return sign * (int(hours) * 60 + int(minutes))


def _unsupported(detected_type: str | None) -> Problem:
    extra = {"detected_type": detected_type} if detected_type else {}
    return Problem(
        415,
        "unsupported_media_type",
        "Not a supported image",
        "Supported are JPEG, PNG, WebP, GIF, TIFF, BMP, JPEG 2000 and AVIF.",
        **extra,
    )
