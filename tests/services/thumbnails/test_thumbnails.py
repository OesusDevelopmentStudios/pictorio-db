# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

import pytest
from PIL import ExifTags, Image

from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

SHA256 = "ab12" + "0" * 60


@pytest.fixture
def thumbnails(tmp_path: Path) -> ThumbnailsService:
    return ThumbnailsService(tmp_path / "thumbnails")


def write_image(
    path: Path, size: tuple[int, int], mode: str = "RGB", image_format: str = "PNG", **options: object
) -> Path:
    Image.new(mode, size).save(path, format=image_format, **options)
    return path


def thumbnail(thumbnails: ThumbnailsService, size: int) -> Image.Image:
    with Image.open(thumbnails.thumbnail_path(SHA256, size)) as image:
        image.load()
        return image


def test_makes_both_sizes_with_the_longest_side_limited(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    thumbnails.create_thumbnails(write_image(tmp_path / "wide.png", (3000, 2000)), SHA256)

    assert thumbnail(thumbnails, 1024).size == (1024, 683)
    assert thumbnail(thumbnails, 256).size == (256, 171)
    assert thumbnail(thumbnails, 256).format == "WEBP"


def test_does_not_enlarge_small_images(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    thumbnails.create_thumbnails(write_image(tmp_path / "small.png", (100, 50)), SHA256)

    assert thumbnail(thumbnails, 1024).size == (100, 50)


def test_turns_sideways_photos_upright(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6  # stored sideways, shown turned by 90°
    photo = write_image(tmp_path / "photo.jpg", (400, 300), image_format="JPEG", exif=exif)

    thumbnails.create_thumbnails(photo, SHA256)

    assert thumbnail(thumbnails, 256).size == (192, 256)


def test_keeps_transparency(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    thumbnails.create_thumbnails(write_image(tmp_path / "logo.png", (64, 64), mode="RGBA"), SHA256)

    assert thumbnail(thumbnails, 256).mode == "RGBA"


def test_converts_print_colours(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    print_image = write_image(tmp_path / "print.jpg", (64, 64), mode="CMYK", image_format="JPEG")

    thumbnails.create_thumbnails(print_image, SHA256)

    assert thumbnail(thumbnails, 256).mode == "RGB"


def test_uses_the_first_frame_of_an_animation(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    frames = [Image.new("RGB", (64, 48), colour) for colour in ("red", "blue")]
    animation = tmp_path / "waves.gif"
    frames[0].save(animation, save_all=True, append_images=frames[1:])

    thumbnails.create_thumbnails(animation, SHA256)

    assert thumbnail(thumbnails, 256).size == (64, 48)


def test_damaged_image_data_is_refused(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    whole = write_image(tmp_path / "whole.jpg", (400, 300), image_format="JPEG")
    damaged = tmp_path / "damaged.jpg"
    damaged.write_bytes(whole.read_bytes()[:400])  # the header is fine, the picture is cut off

    with pytest.raises(Problem) as raised:
        thumbnails.create_thumbnails(damaged, SHA256)

    assert (raised.value.status, raised.value.detail) == (415, "The image data is damaged.")


def test_stores_thumbnails_by_size_and_hash(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    path = thumbnails.thumbnail_path(SHA256, 256)

    assert path == tmp_path / "thumbnails" / "256" / "ab" / f"{SHA256}.webp"


def test_refuses_unknown_sizes(thumbnails: ThumbnailsService) -> None:
    with pytest.raises(ValueError):
        thumbnails.thumbnail_path(SHA256, 512)


def test_leaves_no_partial_files(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    thumbnails.create_thumbnails(write_image(tmp_path / "image.png", (300, 200)), SHA256)

    assert list((tmp_path / "thumbnails").rglob("*.partial")) == []


def test_deletes_both_sizes(thumbnails: ThumbnailsService, tmp_path: Path) -> None:
    thumbnails.create_thumbnails(write_image(tmp_path / "image.png", (300, 200)), SHA256)

    thumbnails.delete_thumbnails(SHA256)

    assert not thumbnails.thumbnail_path(SHA256, 256).exists()
    assert not thumbnails.thumbnail_path(SHA256, 1024).exists()
