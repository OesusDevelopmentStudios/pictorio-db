# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Moving the library's files after a path template change, with real files and the real worker."""

import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
from PIL import ExifTags, Image

from pictorio_db.db import Database
from pictorio_db.services.access import Restrictions
from pictorio_db.services.auth import AuthService, Role
from pictorio_db.services.images import ImageRecord, ImagesService
from pictorio_db.services.importer import ImporterService, UploadMetadata
from pictorio_db.services.jobs import JobInfo, JobKind, JobsService, JobStatus, Relayout
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService


class Library:
    def __init__(self, database: Database, tmp_path: Path) -> None:
        self.library_dir = tmp_path / "library"
        settings = SettingsService(database)
        tags = TagsService(database, lambda: self.storage.path_template_namespaces())
        self.storage = StorageService(database, settings, self.library_dir, tags.namespace_names)
        self.images = ImagesService(database, tags, self.storage)
        thumbnails = ThumbnailsService(tmp_path / "thumbnails")
        self.importer = ImporterService(self.images, tags, self.storage, thumbnails, settings)
        self.jobs = JobsService(database)
        self.relayout = Relayout(self.jobs, self.images)
        self.jobs.register(JobKind.RELAYOUT, self.relayout.run)
        self.admin = AuthService(database).create_user("apo", "correct horse battery", Role.ADMIN)

    def add_image(self, colour: str, tags: tuple[str, ...]) -> ImageRecord:
        """Taken in 2024."""
        incoming = self.importer.new_incoming_path()
        exif = Image.Exif()
        exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = "2024:05:01 10:00:00"
        Image.new("RGB", (8, 8), colour).save(incoming, format="JPEG", exif=exif)
        return self.importer.import_image(incoming, UploadMetadata(f"{colour}.jpg", tags=tags), None, Restrictions([]))

    def run_relayout(self) -> JobInfo:
        job = self.relayout.start(self.admin.id)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.jobs.get_job(job.id, self.admin)
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return job

            time.sleep(0.01)

        raise AssertionError("The relayout did not finish in time")

    def folders(self) -> list[str]:
        return sorted(str(PurePosixPath(record.storage_path).parent) for record in self.all_images())

    def all_images(self) -> list[ImageRecord]:
        return self.images.get_images(self.images.all_image_ids())


@pytest.fixture
def library(database: Database, tmp_path: Path) -> Iterator[Library]:
    started = Library(database, tmp_path)
    started.jobs.start()
    yield started
    started.jobs.stop()


def test_moves_every_file_to_the_new_layout(library: Library) -> None:
    library.add_image("red", ("category:photo", "author:sample_artist"))
    library.add_image("green", ("category:artwork",))
    assert library.folders() == ["artwork/_unknown/2024", "photo/sample_artist/2024"]

    library.storage.set_path_template("{year}/{category}")
    job = library.run_relayout()

    assert job.status == JobStatus.DONE
    assert job.result == {"moved": 2, "unchanged": 0, "failed": []}
    assert (job.progress_done, job.progress_total) == (2, 2)
    assert library.folders() == ["2024/artwork", "2024/photo"]
    assert all((library.library_dir / record.storage_path).is_file() for record in library.all_images())
    assert not (library.library_dir / "photo").exists()  # the old folders are gone


def test_files_already_in_place_stay(library: Library) -> None:
    library.add_image("red", ("category:photo",))
    library.add_image("green", ("category:artwork",))

    assert library.run_relayout().result == {"moved": 0, "unchanged": 2, "failed": []}


def test_failed_move_is_reported_and_the_rest_moves(
    library: Library, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    stuck = library.add_image("red", ("category:photo",))
    library.add_image("green", ("category:photo",))
    move_image_file = library.storage.move_image_file

    def disk_error_for_one(image_id: int, to_path: PurePosixPath) -> None:
        if image_id == stuck.id:
            raise OSError("disk unavailable")

        move_image_file(image_id, to_path)

    monkeypatch.setattr(library.storage, "move_image_file", disk_error_for_one)
    library.storage.set_path_template("{year}")
    job = library.run_relayout()

    assert job.result == {"moved": 1, "unchanged": 0, "failed": [{"image_id": stuck.id, "code": "move_failed"}]}
    assert library.images.get_image(stuck.id).storage_path == stuck.storage_path
    assert (library.library_dir / stuck.storage_path).is_file()
    assert "Could not move the file of image" in caplog.text
