# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Changing the tags of images, with real files: a change to a folder-forming tag moves the file."""

import logging
from pathlib import Path

import pytest
from PIL import ExifTags, Image

from pictorio_db.db import Database
from pictorio_db.services.images import ImageRecord, ImagesService
from pictorio_db.services.importer import ImporterService, UploadMetadata
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem


class Library:
    def __init__(self, database: Database, tmp_path: Path) -> None:
        self.library_dir = tmp_path / "library"
        settings = SettingsService(database)
        tags = TagsService(database, lambda: self.storage.path_template_namespaces())
        self.storage = StorageService(database, settings, self.library_dir, tags.namespace_names)
        self.images = ImagesService(database, tags, self.storage)
        thumbnails = ThumbnailsService(tmp_path / "thumbnails")
        self.importer = ImporterService(self.images, tags, self.storage, thumbnails, settings)

    def add_image(self, colour: str, tags: tuple[str, ...]) -> ImageRecord:
        """Taken in 2024, so its folder is <category>/<author>/2024."""
        incoming = self.importer.new_incoming_path()
        exif = Image.Exif()
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2024:05:01 10:00:00"
        Image.new("RGB", (8, 8), colour).save(incoming, format="JPEG", exif=exif)
        return self.importer.import_image(incoming, UploadMetadata(f"{colour}.jpg", tags=tags), user_id=None)

    def folder_of(self, record: ImageRecord) -> str:
        return str(Path(record.storage_path).parent)

    def file_exists(self, record: ImageRecord) -> bool:
        return (self.library_dir / record.storage_path).is_file()


@pytest.fixture
def library(database: Database, tmp_path: Path) -> Library:
    return Library(database, tmp_path)


def tag_texts(record: ImageRecord) -> list[str]:
    return [str(tag) for tag in record.tags]


def problem_of(action: object) -> Problem:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]
    return raised.value


# --- One image

def test_adds_and_removes_tags(library: Library) -> None:
    image = library.add_image("red", ("category:photo", "summer", "beach"))

    changed = library.images.change_tags(
        image.id, add_tags=["Sunset Sky", "author:sample_artist"], remove_tags=["beach"]
    )

    assert tag_texts(changed) == ["author:sample_artist", "category:photo", "general:summer", "general:sunset_sky"]
    assert changed.updated_at >= image.updated_at


def test_removing_a_tag_the_image_lacks_changes_nothing(library: Library) -> None:
    image = library.add_image("red", ("summer",))

    unchanged = library.images.change_tags(image.id, add_tags=[], remove_tags=["winter"])

    assert unchanged == image  # not even updated_at


def test_tag_both_added_and_removed_stays(library: Library) -> None:
    image = library.add_image("red", ("summer",))

    changed = library.images.change_tags(image.id, add_tags=["summer"], remove_tags=["summer"])

    assert tag_texts(changed) == ["general:summer"]


def test_new_tag_in_a_single_value_namespace_replaces_the_old_one(library: Library) -> None:
    image = library.add_image("red", ("category:photo",))

    changed = library.images.change_tags(image.id, add_tags=["category:artwork"], remove_tags=[])

    assert tag_texts(changed) == ["category:artwork"]


def test_moves_the_file_when_its_folder_changes(library: Library) -> None:
    image = library.add_image("red", ("category:photo",))
    assert library.folder_of(image) == "photo/_unknown/2024"

    changed = library.images.change_tags(
        image.id, add_tags=["category:artwork", "author:sample_artist"], remove_tags=[]
    )

    assert library.folder_of(changed) == "artwork/sample_artist/2024"
    assert Path(changed.storage_path).name == Path(image.storage_path).name
    assert library.file_exists(changed)
    assert not (library.library_dir / "photo").exists()  # the empty old folders are gone


def test_keeps_the_file_when_the_folder_stays(library: Library) -> None:
    image = library.add_image("red", ("category:photo",))

    changed = library.images.change_tags(image.id, add_tags=["summer"], remove_tags=[])

    assert changed.storage_path == image.storage_path


def test_file_name_taken_in_the_new_folder_gets_a_number(library: Library) -> None:
    image = library.add_image("red", ("category:photo",))
    occupied = library.library_dir / "artwork/_unknown/2024" / Path(image.storage_path).name
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"another file")

    changed = library.images.change_tags(image.id, add_tags=["category:artwork"], remove_tags=[])

    assert changed.storage_path.endswith("_2.jpg")
    assert occupied.read_bytes() == b"another file"


def test_invalid_tag_changes_nothing(library: Library) -> None:
    image = library.add_image("red", ("summer",))

    problem = problem_of(lambda: library.images.change_tags(image.id, add_tags=["ok", "a|b"], remove_tags=[]))

    assert (problem.status, problem.code) == (422, "invalid_tag")
    assert library.images.get_image(image.id) == image


def test_unknown_image_is_not_found(library: Library) -> None:
    assert problem_of(lambda: library.images.change_tags(999, add_tags=["summer"], remove_tags=[])).status == 404


def test_failed_move_keeps_the_tags_and_the_file_where_recorded(
    library: Library, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    image = library.add_image("red", ("category:photo",))

    def disk_unavailable(*_arguments: object) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(library.storage, "move_image_file", disk_unavailable)
    with caplog.at_level(logging.ERROR):
        changed = library.images.change_tags(image.id, add_tags=["category:artwork"], remove_tags=[])

    assert tag_texts(changed) == ["category:artwork"]
    assert changed.storage_path == image.storage_path
    assert library.file_exists(changed)
    assert "Could not move the file" in caplog.text


# --- Many images

def test_changes_many_images_and_moves_their_files(library: Library) -> None:
    images = [library.add_image(colour, ("category:photo",)) for colour in ("red", "green", "blue")]

    updated = library.images.change_tags_of_many(
        [image.id for image in images], add_tags=["author:sample_artist", "album:trip"], remove_tags=[]
    )

    assert updated == 3
    for record in library.images.get_images([image.id for image in images]):
        assert tag_texts(record) == ["album:trip", "author:sample_artist", "category:photo"]
        assert library.folder_of(record) == "photo/sample_artist/2024"
        assert library.file_exists(record)


def test_unknown_id_changes_none_of_the_images(library: Library) -> None:
    image = library.add_image("red", ("summer",))

    problem = problem_of(
        lambda: library.images.change_tags_of_many([image.id, 999], add_tags=["album:trip"], remove_tags=[])
    )

    assert (problem.status, problem.detail) == (404, "One of the images does not exist.")
    assert library.images.get_image(image.id) == image


def test_repeated_ids_count_once(library: Library) -> None:
    image = library.add_image("red", ())

    assert library.images.change_tags_of_many([image.id, image.id], add_tags=["summer"], remove_tags=[]) == 1


def test_images_that_already_have_the_tag_are_not_touched(library: Library) -> None:
    tagged = library.add_image("red", ("summer",))
    untagged = library.add_image("green", ())

    library.images.change_tags_of_many([tagged.id, untagged.id], add_tags=["summer"], remove_tags=[])

    assert library.images.get_image(tagged.id).updated_at == tagged.updated_at
    assert tag_texts(library.images.get_image(untagged.id)) == ["general:summer"]
