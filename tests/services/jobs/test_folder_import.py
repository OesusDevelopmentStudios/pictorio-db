# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Folder import jobs with the real services and worker, on temporary import and library folders."""

import io
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image

from pictorio_db.db import Database
from pictorio_db.services.auth import AuthService, Role
from pictorio_db.services.images import ImagesService
from pictorio_db.services.importer import ImporterService
from pictorio_db.services.jobs import FolderImport, JobInfo, JobKind, JobsService, JobStatus
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem


class Server:
    def __init__(self, database: Database, tmp_path: Path, import_dir: Path | None) -> None:
        self.import_dir = import_dir
        self.library_dir = tmp_path / "library"
        settings = SettingsService(database)
        tags = TagsService(database, lambda: self.storage.path_template_namespaces())
        self.storage = StorageService(database, settings, self.library_dir, tags.namespace_names)
        self.images = ImagesService(database, tags, self.storage)
        thumbnails = ThumbnailsService(tmp_path / "thumbnails")
        importer = ImporterService(self.images, tags, self.storage, thumbnails, settings)
        self.jobs = JobsService(database)
        self.folder_import = FolderImport(self.jobs, importer, tags, import_dir)
        self.jobs.register(JobKind.FOLDER_IMPORT, self.folder_import.run)
        self.admin = AuthService(database).create_user("apo", "correct horse battery", Role.ADMIN)

    def import_folder(
        self, source_subdir: str, remove_originals: bool = False, tags: list[str] | None = None
    ) -> JobInfo:
        """Starts the import and waits for it to finish."""
        job = self.folder_import.start(source_subdir, remove_originals, tags or [], self.admin.id)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.jobs.get_job(job.id, self.admin)
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return job

            time.sleep(0.01)

        raise AssertionError("The import did not finish in time")

    def library_count(self) -> int:
        return len([path for path in self.library_dir.rglob("*.*") if ".incoming" not in path.parts])


@pytest.fixture
def import_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "import"
    folder.mkdir()
    return folder


@pytest.fixture
def server(database: Database, tmp_path: Path, import_dir: Path) -> Iterator[Server]:
    started = Server(database, tmp_path, import_dir)
    started.jobs.start()
    yield started
    started.jobs.stop()


def write_jpeg(path: Path, colour: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="JPEG")
    path.write_bytes(buffer.getvalue())
    return path


def problem_of(action: object) -> Problem:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]
    return raised.value


@pytest.fixture
def trip(import_dir: Path) -> Path:
    """trip/: two photos, one of them twice, a video and a note; and a subfolder with one more photo."""
    folder = import_dir / "trip"
    write_jpeg(folder / "beach.jpg", "blue")
    write_jpeg(folder / "copy of beach.jpg", "blue")
    write_jpeg(folder / "day 2" / "hills.jpg", "green")
    (folder / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (folder / "notes.txt").write_text("sunny")
    return folder


# --- Importing

def test_imports_the_folder_and_its_subfolders(server: Server, trip: Path) -> None:
    job = server.import_folder("trip", tags=["album:trip"])

    assert job.status == JobStatus.DONE
    assert job.result == {"imported": 2, "duplicates": 1, "unsupported": 2, "failed": []}
    assert (job.progress_done, job.progress_total) == (5, 5)
    assert server.library_count() == 2
    assert len(list(trip.rglob("*.*"))) == 5  # the originals stay


def test_imported_images_get_the_tags_and_the_admin(server: Server, trip: Path) -> None:
    server.import_folder("trip/day 2", tags=["album:trip", "summer"])

    [record] = server.images.get_images([1])
    assert [str(tag) for tag in record.tags] == ["album:trip", "general:summer"]
    assert (record.original_filename, record.imported_by_user_id) == ("hills.jpg", server.admin.id)
    assert record.taken_at_source == "file_mtime"


def test_whole_import_folder_is_imported_with_an_empty_path(server: Server, trip: Path, import_dir: Path) -> None:
    write_jpeg(import_dir / "loose.jpg", "red")

    assert server.import_folder("").result["imported"] == 3


def test_importing_again_finds_only_duplicates(server: Server, trip: Path) -> None:
    server.import_folder("trip")

    assert server.import_folder("trip").result == {"imported": 0, "duplicates": 3, "unsupported": 2, "failed": []}


def test_damaged_image_stays_in_the_folder(server: Server, import_dir: Path) -> None:
    damaged = write_jpeg(import_dir / "inbox" / "damaged.jpg", "red")
    whole = damaged.read_bytes()
    damaged.write_bytes(whole[: len(whole) // 2])

    job = server.import_folder("inbox", remove_originals=True)

    assert job.result["unsupported"] == 1
    assert damaged.exists()


def test_links_are_not_followed(server: Server, import_dir: Path, tmp_path: Path) -> None:
    outside = write_jpeg(tmp_path / "private" / "secret.jpg", "red")
    (import_dir / "inbox").mkdir()
    (import_dir / "inbox" / "secret.jpg").symlink_to(outside)
    (import_dir / "inbox" / "private").symlink_to(outside.parent)

    job = server.import_folder("inbox")

    assert job.result["imported"] == 0
    assert job.result["failed"] == [
        {"path": "inbox/private", "code": "not_a_regular_file"},
        {"path": "inbox/secret.jpg", "code": "not_a_regular_file"},
    ]


# --- Removing the originals

def test_removes_imported_files_and_duplicates_only(server: Server, trip: Path) -> None:
    job = server.import_folder("trip", remove_originals=True)

    assert job.result["imported"] == 2
    assert sorted(path.name for path in trip.rglob("*.*")) == ["clip.mp4", "notes.txt"]


def test_original_that_cannot_be_removed_is_reported(
    server: Server, trip: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unlink = Path.unlink

    def refuse_in_the_import_folder(path: Path, missing_ok: bool = False) -> None:
        if trip in path.parents:
            raise PermissionError("read-only")

        unlink(path, missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse_in_the_import_folder)
    job = server.import_folder("trip/day 2", remove_originals=True)

    assert job.result["imported"] == 1
    assert job.result["failed"] == [{"path": "trip/day 2/hills.jpg", "code": "not_removed"}]


def test_read_only_folder_cannot_have_its_originals_removed(server: Server, trip: Path) -> None:
    trip.chmod(0o555)
    try:
        problem = problem_of(lambda: server.folder_import.start("trip", True, [], server.admin.id))
    finally:
        trip.chmod(0o755)

    assert (problem.status, problem.title) == (422, "Folder is read-only")


# --- Refused before the job starts

@pytest.mark.parametrize("source_subdir", ["/etc", "../library", "trip/../../library", "outside"])
def test_folders_outside_the_import_folder_are_refused(
    server: Server, trip: Path, tmp_path: Path, source_subdir: str
) -> None:
    (trip.parent / "outside").symlink_to(tmp_path)

    problem = problem_of(lambda: server.folder_import.start(source_subdir, False, [], server.admin.id))

    assert (problem.status, problem.title) == (422, "Invalid folder")
    assert server.jobs.list_jobs(server.admin) == []


@pytest.mark.parametrize("source_subdir", ["holiday", "trip/beach.jpg"])
def test_missing_folder_is_refused(server: Server, trip: Path, source_subdir: str) -> None:
    problem = problem_of(lambda: server.folder_import.start(source_subdir, False, [], server.admin.id))

    assert (problem.status, problem.title) == (422, "Folder not found")


def test_invalid_tag_is_refused(server: Server, trip: Path) -> None:
    problem = problem_of(lambda: server.folder_import.start("trip", False, ["a|b"], server.admin.id))

    assert problem.code == "invalid_tag"


def test_without_an_import_folder_imports_are_off(database: Database, tmp_path: Path) -> None:
    server = Server(database, tmp_path, import_dir=None)

    problem = problem_of(lambda: server.folder_import.start("", False, [], server.admin.id))

    assert (problem.status, problem.code) == (409, "import_dir_not_set")


def test_folder_removed_before_the_job_runs_fails_the_job(server: Server, trip: Path) -> None:
    server.jobs.stop()
    job = server.folder_import.start("trip/day 2", False, [], server.admin.id)
    (trip / "day 2" / "hills.jpg").unlink()
    (trip / "day 2").rmdir()
    server.jobs.start()

    deadline = time.monotonic() + 10
    while server.jobs.get_job(job.id, server.admin).status != JobStatus.FAILED and time.monotonic() < deadline:
        time.sleep(0.01)

    assert server.jobs.get_job(job.id, server.admin).error == "Folder not found. The import folder has no 'trip/day 2'."
