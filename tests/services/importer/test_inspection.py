# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Every test image is generated here with Pillow; no image files are kept in the repository."""

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from pictorio_db.services.importer import file_sha256, inspect_image
from pictorio_db.services.importer._inspection import _parse_utc_offset
from pictorio_db.utils.problems import Problem


def write_image(
    path: Path,
    image_format: str,
    size: tuple[int, int] = (40, 30),
    exif: Image.Exif | None = None,
) -> Path:
    image = Image.new("RGB", size, (30, 120, 200))
    options: dict[str, object] = {"exif": exif} if exif is not None else {}
    if image_format == "MPO":
        options["save_all"] = True
        options["append_images"] = [Image.new("RGB", size)]

    image.save(path, format=image_format, **options)
    return path


def exif_with(
    original: str | None = None,
    digitized: str | None = None,
    offset: str | None = None,
    orientation: int | None = None,
) -> Image.Exif:
    exif = Image.Exif()
    if orientation is not None:
        exif[ExifTags.Base.Orientation] = orientation

    photo_tags = exif.get_ifd(ExifTags.IFD.Exif)
    for tag, value in (
        (ExifTags.Base.DateTimeOriginal, original),
        (ExifTags.Base.DateTimeDigitized, digitized),
        (ExifTags.Base.OffsetTimeOriginal, offset),
    ):
        if value is not None:
            photo_tags[tag] = value

    return exif


def unsupported_problem(path: Path) -> Problem:
    with pytest.raises(Problem) as raised:
        inspect_image(path)

    assert (raised.value.status, raised.value.code) == (415, "unsupported_media_type")
    return raised.value


# --- Type

@pytest.mark.parametrize(
    ("image_format", "mime_type", "extension"),
    [
        ("JPEG", "image/jpeg", "jpg"),
        ("MPO", "image/jpeg", "jpg"),
        ("PNG", "image/png", "png"),
        ("WEBP", "image/webp", "webp"),
        ("GIF", "image/gif", "gif"),
        ("TIFF", "image/tiff", "tiff"),
        ("BMP", "image/bmp", "bmp"),
        ("JPEG2000", "image/jp2", "jp2"),
        ("AVIF", "image/avif", "avif"),
    ],
)
def test_recognises_supported_types(tmp_path: Path, image_format: str, mime_type: str, extension: str) -> None:
    facts = inspect_image(write_image(tmp_path / "upload", image_format))

    assert (facts.type.mime_type, facts.type.extension) == (mime_type, extension)


def test_type_comes_from_the_content_not_the_name(tmp_path: Path) -> None:
    facts = inspect_image(write_image(tmp_path / "holiday.jpg", "PNG"))

    assert facts.type.mime_type == "image/png"


def test_rejects_files_that_are_not_images(tmp_path: Path) -> None:
    text_file = tmp_path / "notes.jpg"
    text_file.write_text("not an image")

    assert "detected_type" not in unsupported_problem(text_file).extra


def test_names_the_detected_type_of_unsupported_images(tmp_path: Path) -> None:
    icon = write_image(tmp_path / "favicon", "ICO", size=(32, 32))

    assert unsupported_problem(icon).extra["detected_type"] == "image/x-icon"


def test_rejects_a_broken_image(tmp_path: Path) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(write_image(tmp_path / "whole.png", "PNG").read_bytes()[:20])

    unsupported_problem(broken)


# --- Size

def test_reads_width_and_height(tmp_path: Path) -> None:
    facts = inspect_image(write_image(tmp_path / "landscape", "PNG", size=(40, 30)))

    assert (facts.width, facts.height) == (40, 30)


@pytest.mark.parametrize(("orientation", "shown_size"), [(1, (40, 30)), (3, (40, 30)), (6, (30, 40)), (8, (30, 40))])
def test_size_is_as_shown_after_the_exif_orientation(
    tmp_path: Path, orientation: int, shown_size: tuple[int, int]
) -> None:
    exif = exif_with(orientation=orientation)

    facts = inspect_image(write_image(tmp_path / "photo", "JPEG", size=(40, 30), exif=exif))

    assert (facts.width, facts.height) == shown_size


# --- Date taken

def test_reads_date_taken_and_its_utc_offset(tmp_path: Path) -> None:
    exif = exif_with(original="2024:07:14 18:30:05", offset="+02:00")

    facts = inspect_image(write_image(tmp_path / "photo", "JPEG", exif=exif))

    assert facts.taken_at == datetime(2024, 7, 14, 18, 30, 5)
    assert facts.taken_at_utc_offset_minutes == 120


def test_falls_back_to_date_digitized(tmp_path: Path) -> None:
    facts = inspect_image(write_image(tmp_path / "scan", "JPEG", exif=exif_with(digitized="2023:01:02 08:00:00")))

    assert facts.taken_at == datetime(2023, 1, 2, 8, 0, 0)
    assert facts.taken_at_utc_offset_minutes is None


def test_unset_camera_clock_is_no_date(tmp_path: Path) -> None:
    facts = inspect_image(write_image(tmp_path / "photo", "JPEG", exif=exif_with(original="0000:00:00 00:00:00")))

    assert facts.taken_at is None


def test_image_without_exif_has_no_date(tmp_path: Path) -> None:
    facts = inspect_image(write_image(tmp_path / "drawing", "PNG"))

    assert (facts.taken_at, facts.taken_at_utc_offset_minutes) == (None, None)


@pytest.mark.parametrize(
    ("text", "minutes"),
    [("+02:00", 120), ("-05:30", -330), ("+00:00", 0), ("Z", None), ("02:00", None), ("+2:00", None), (None, None)],
)
def test_parses_utc_offsets(text: str | None, minutes: int | None) -> None:
    assert _parse_utc_offset(text) == minutes


# --- Hash

def test_sha256_of_the_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "data"
    path.write_bytes(b"x" * 3_000_000)  # more than one read chunk

    assert file_sha256(path) == hashlib.sha256(b"x" * 3_000_000).hexdigest()
