# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The import flow with the real services on a temporary database, library and thumbnail folder."""

import hashlib
from datetime import datetime
from pathlib import Path

import pytest
from PIL import ExifTags, Image
from sqlalchemy import func, select

from pictorio_db.db import Database
from pictorio_db.db.models import Image as ImageRow
from pictorio_db.db.models import User
from pictorio_db.services.images import ImagesService
from pictorio_db.services.importer import DEFAULT_MAX_UPLOAD_BYTES, ImporterService, UploadMetadata
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

IMPORT_TIME = datetime(2026, 11, 12, 9, 30)


class Library:
    """The services the importer needs, and the folders they use."""

    def __init__(self, database: Database, tmp_path: Path) -> None:
        self.database = database
        self.library_dir = tmp_path / "library"
        self.thumbnails_dir = tmp_path / "thumbnails"
        self.settings = SettingsService(database)
        self.tags = TagsService(database, lambda: self.storage.path_template_namespaces())
        self.storage = StorageService(database, self.settings, self.library_dir, self.tags.namespace_names)
        self.thumbnails = ThumbnailsService(self.thumbnails_dir)
        self.images = ImagesService(database)
        self.importer = ImporterService(
            self.images, self.tags, self.storage, self.thumbnails, self.settings, now=lambda: IMPORT_TIME
        )

    def incoming_image(self, size: tuple[int, int] = (40, 30), taken: str | None = None, colour: str = "teal") -> Path:
        incoming = self.importer.new_incoming_path()
        exif = Image.Exif()
        if taken is not None:
            exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = taken

        Image.new("RGB", size, colour).save(incoming, format="JPEG", exif=exif)
        return incoming

    def library_files(self) -> list[str]:
        return sorted(
            str(path.relative_to(self.library_dir))
            for path in self.library_dir.rglob("*")
            if path.is_file() and ".incoming" not in path.parts
        )

    def assert_nothing_stored(self) -> None:
        assert self.library_files() == []
        assert list((self.library_dir / ".incoming").iterdir()) == []
        assert not self.thumbnails_dir.exists() or not any(self.thumbnails_dir.rglob("*.webp"))
        with self.database.session() as session:
            assert session.scalar(select(func.count()).select_from(ImageRow)) == 0


@pytest.fixture
def library(database: Database, tmp_path: Path) -> Library:
    return Library(database, tmp_path)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refused(action: object) -> Problem:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]
    return raised.value


# --- Imports that succeed

def test_stores_the_image_where_its_tags_and_date_say(library: Library) -> None:
    incoming = library.incoming_image(taken="2024:07:14 18:30:05")
    sha256 = sha256_of(incoming)
    file_size = incoming.stat().st_size
    metadata = UploadMetadata("beach.JPG", tags=("category:photo", "author:Sample Artist", "summer"))

    record = library.importer.import_image(incoming, metadata, user_id=None)

    expected_path = f"photo/sample_artist/2024/beach_{sha256[:8]}.jpg"
    assert record.storage_path == expected_path
    assert library.library_files() == [expected_path]
    assert not incoming.exists()
    assert (record.mime_type, record.width, record.height, record.file_size) == ("image/jpeg", 40, 30, file_size)
    assert (record.taken_at, record.taken_at_source) == (datetime(2024, 7, 14, 18, 30, 5), "exif")
    assert [str(tag) for tag in record.tags] == ["author:sample_artist", "category:photo", "general:summer"]
    assert library.thumbnails.thumbnail_path(sha256, 256).exists()


def test_records_who_imported_the_image(library: Library) -> None:
    with library.database.session() as session:
        user = User(username="kid", password_hash="x", role="user", created_at=IMPORT_TIME)
        session.add(user)
        session.commit()
        user_id = user.id

    record = library.importer.import_image(library.incoming_image(), UploadMetadata("a.jpg"), user_id=user_id)

    assert record.imported_by_user_id == user_id


def test_date_comes_from_the_file_time_without_exif(library: Library) -> None:
    metadata = UploadMetadata("scan.jpg", file_mtime=datetime(2019, 3, 1, 10, 0))

    record = library.importer.import_image(library.incoming_image(), metadata, user_id=None)

    assert (record.taken_at, record.taken_at_source) == (datetime(2019, 3, 1, 10, 0), "file_mtime")


def test_date_is_the_import_time_without_anything_else(library: Library) -> None:
    record = library.importer.import_image(library.incoming_image(), UploadMetadata("scan.jpg"), user_id=None)

    assert (record.taken_at, record.taken_at_source) == (IMPORT_TIME, "import_time")


def test_later_tag_replaces_earlier_one_in_single_value_namespace(library: Library) -> None:
    metadata = UploadMetadata("art.jpg", tags=("category:photo", "category:artwork"))

    record = library.importer.import_image(library.incoming_image(), metadata, user_id=None)

    assert [str(tag) for tag in record.tags] == ["category:artwork"]
    assert record.storage_path.startswith("artwork/")


def test_image_without_tags_goes_to_unknown_folders(library: Library) -> None:
    record = library.importer.import_image(library.incoming_image(), UploadMetadata("a.jpg"), user_id=None)

    assert record.storage_path.startswith("_unknown/_unknown/2026/")


def test_client_checksum_may_be_in_capitals(library: Library) -> None:
    incoming = library.incoming_image()
    metadata = UploadMetadata("a.jpg", client_sha256=sha256_of(incoming).upper())

    library.importer.import_image(incoming, metadata, user_id=None)


def test_taken_file_name_gets_a_number(library: Library) -> None:
    incoming = library.incoming_image()
    taken_path = library.library_dir / "_unknown/_unknown/2026" / f"a_{sha256_of(incoming)[:8]}.jpg"
    taken_path.parent.mkdir(parents=True)
    taken_path.write_bytes(b"a different file")

    record = library.importer.import_image(incoming, UploadMetadata("a.jpg"), user_id=None)

    assert record.storage_path.endswith("_2.jpg")


# --- Imports that are refused; nothing may be left behind

def test_refuses_a_file_damaged_on_the_way(library: Library) -> None:
    metadata = UploadMetadata("a.jpg", client_sha256="0" * 64)

    problem = refused(lambda: library.importer.import_image(library.incoming_image(), metadata, user_id=None))

    assert (problem.status, problem.code) == (422, "checksum_mismatch")
    library.assert_nothing_stored()


def test_refuses_a_duplicate_and_keeps_the_existing_image(library: Library) -> None:
    first = library.importer.import_image(library.incoming_image(), UploadMetadata("a.jpg"), user_id=None)
    again = library.incoming_image()  # the same picture, so the same bytes

    problem = refused(
        lambda: library.importer.import_image(again, UploadMetadata("b.jpg", tags=("summer",)), user_id=None)
    )

    assert (problem.status, problem.code) == (409, "duplicate_image")
    assert problem.extra["existing_image_id"] == first.id
    assert not again.exists()
    assert library.library_files() == [first.storage_path]
    assert library.thumbnails.thumbnail_path(first.sha256, 256).exists()
    assert library.images.get_image(first.id).tags == []


def test_refuses_an_invalid_tag(library: Library) -> None:
    metadata = UploadMetadata("a.jpg", tags=("rating:sfw", "a|b"))

    problem = refused(lambda: library.importer.import_image(library.incoming_image(), metadata, user_id=None))

    assert (problem.status, problem.code) == (422, "invalid_tag")
    library.assert_nothing_stored()


def test_refuses_a_file_that_is_not_an_image(library: Library) -> None:
    incoming = library.importer.new_incoming_path()
    incoming.write_text("not an image")

    problem = refused(lambda: library.importer.import_image(incoming, UploadMetadata("notes.jpg"), user_id=None))

    assert (problem.status, problem.code) == (415, "unsupported_media_type")
    library.assert_nothing_stored()


def test_refuses_damaged_image_data(library: Library) -> None:
    incoming = library.incoming_image(size=(400, 300))
    whole = incoming.read_bytes()
    incoming.write_bytes(whole[: len(whole) // 2])  # the header is fine, the picture is cut off

    problem = refused(lambda: library.importer.import_image(incoming, UploadMetadata("a.jpg"), user_id=None))

    assert problem.detail == "The image data is damaged."
    library.assert_nothing_stored()


def test_removes_the_stored_file_when_recording_fails(library: Library, monkeypatch: pytest.MonkeyPatch) -> None:
    def database_fails(*_arguments: object) -> None:
        raise RuntimeError("database is gone")

    monkeypatch.setattr(library.images, "create_image", database_fails)

    with pytest.raises(RuntimeError):
        library.importer.import_image(library.incoming_image(), UploadMetadata("a.jpg"), user_id=None)

    library.assert_nothing_stored()
    assert [path.name for path in library.library_dir.iterdir()] == [".incoming"]  # empty folders removed too


# --- Settings and housekeeping

def test_upload_limit_has_a_default_and_can_be_changed(library: Library) -> None:
    assert library.importer.max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES

    library.settings.set("max_upload_bytes", 1024)

    assert library.importer.max_upload_bytes() == 1024


def test_interrupted_uploads_are_removed(library: Library) -> None:
    leftover = library.incoming_image()

    library.storage.clean_incoming()

    assert not leftover.exists()
