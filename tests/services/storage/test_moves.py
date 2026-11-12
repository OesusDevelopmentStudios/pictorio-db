# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Moving image files, and finishing moves that a crash interrupted. A crash is simulated by an
exception at a chosen step; a new StorageService then plays the part of the restarted server."""

import errno
import logging
import os
from datetime import datetime
from pathlib import Path, PurePosixPath

import pytest
from sqlalchemy import select

from pictorio_db.db import Database
from pictorio_db.db.models import FileMove, Image
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.storage import _files, _service

OLD_PATH = PurePosixPath("photo/_unknown/2024/beach_3fa2b1c9.jpg")
NEW_PATH = PurePosixPath("photo/sample_artist/2024/beach_3fa2b1c9.jpg")
CONTENT = b"image bytes"


class SimulatedCrash(Exception):
    """Not an OSError, so no error handling runs: as if the server stopped at this point."""


@pytest.fixture
def library_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "library"
    folder.mkdir()
    return folder


def new_storage(database: Database, library_dir: Path) -> StorageService:
    return StorageService(database, SettingsService(database), library_dir, lambda: set())


@pytest.fixture
def storage(database: Database, library_dir: Path) -> StorageService:
    return new_storage(database, library_dir)


@pytest.fixture
def image_id(database: Database, library_dir: Path) -> int:
    """An image whose file is at OLD_PATH."""
    file_path = library_dir / OLD_PATH
    file_path.parent.mkdir(parents=True)
    file_path.write_bytes(CONTENT)
    moment = datetime(2026, 11, 12, 12, 0)
    image = Image(
        sha256="3fa2b1c9".ljust(64, "0"),
        storage_path=str(OLD_PATH),
        original_filename="beach.jpg",
        mime_type="image/jpeg",
        width=1,
        height=1,
        file_size=len(CONTENT),
        taken_at=moment,
        taken_at_source="import_time",
        imported_at=moment,
        updated_at=moment,
    )
    with database.session() as session:
        session.add(image)
        session.commit()
        return image.id


def stored_path(database: Database, image_id: int) -> str:
    with database.session() as session:
        return session.get_one(Image, image_id).storage_path


def journal(database: Database) -> list[tuple[str, str]]:
    with database.session() as session:
        return [(move.from_path, move.to_path) for move in session.scalars(select(FileMove))]


def restart_and_replay(database: Database, library_dir: Path) -> int:
    return new_storage(database, library_dir).finish_interrupted_moves()


def force_copy_across_filesystems(monkeypatch: pytest.MonkeyPatch) -> None:
    def rename_fails_across_filesystems(source: Path, target: Path) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(_files.os, "rename", rename_fails_across_filesystems)


def crash(*_arguments: object) -> None:
    raise SimulatedCrash


# --- Moves that go well

def test_moves_the_file_and_records_the_new_path(
    storage: StorageService, database: Database, library_dir: Path, image_id: int
) -> None:
    storage.move_image_file(image_id, NEW_PATH)

    assert (library_dir / NEW_PATH).read_bytes() == CONTENT
    assert not (library_dir / OLD_PATH).exists()
    assert stored_path(database, image_id) == str(NEW_PATH)
    assert journal(database) == []


def test_removes_folders_left_empty_but_not_the_library(
    storage: StorageService, library_dir: Path, image_id: int
) -> None:
    storage.move_image_file(image_id, PurePosixPath("beach_3fa2b1c9.jpg"))

    assert not (library_dir / "photo").exists()
    assert library_dir.is_dir()


def test_keeps_folders_with_other_files(storage: StorageService, library_dir: Path, image_id: int) -> None:
    (library_dir / OLD_PATH.parent / "other.jpg").write_bytes(b"other")

    storage.move_image_file(image_id, NEW_PATH)

    assert (library_dir / OLD_PATH.parent / "other.jpg").exists()


def test_copies_across_filesystems(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_copy_across_filesystems(monkeypatch)

    storage.move_image_file(image_id, NEW_PATH)

    assert (library_dir / NEW_PATH).read_bytes() == CONTENT
    assert not (library_dir / OLD_PATH).exists()
    assert not _files.partial_path(library_dir / NEW_PATH).exists()
    assert stored_path(database, image_id) == str(NEW_PATH)


# --- Moves that fail

def test_never_overwrites_a_file(
    storage: StorageService, database: Database, library_dir: Path, image_id: int
) -> None:
    (library_dir / NEW_PATH).parent.mkdir(parents=True)
    (library_dir / NEW_PATH).write_bytes(b"another image")

    with pytest.raises(FileExistsError):
        storage.move_image_file(image_id, NEW_PATH)

    assert (library_dir / NEW_PATH).read_bytes() == b"another image"
    assert (library_dir / OLD_PATH).read_bytes() == CONTENT
    assert stored_path(database, image_id) == str(OLD_PATH)
    assert journal(database) == []


def test_failed_move_changes_nothing(
    storage: StorageService, database: Database, library_dir: Path, image_id: int
) -> None:
    (library_dir / OLD_PATH).unlink()  # e.g. removed by hand

    with pytest.raises(FileNotFoundError):
        storage.move_image_file(image_id, NEW_PATH)

    assert stored_path(database, image_id) == str(OLD_PATH)
    assert journal(database) == []


@pytest.mark.parametrize("path", ["../outside.jpg", "/etc/passwd", "photo/../../outside.jpg"])
def test_paths_cannot_leave_the_library(storage: StorageService, path: str) -> None:
    with pytest.raises(ValueError):
        storage.absolute_path(path)


# --- A crash between the steps

def test_crash_before_the_file_moved(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_service, "move_file", crash)
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)
    assert journal(database) == [(str(OLD_PATH), str(NEW_PATH))]

    assert restart_and_replay(database, library_dir) == 1

    assert (library_dir / OLD_PATH).read_bytes() == CONTENT
    assert stored_path(database, image_id) == str(OLD_PATH)
    assert journal(database) == []


def test_crash_after_the_file_moved(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage, "_finish_move", crash)
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)
    assert stored_path(database, image_id) == str(OLD_PATH)  # the database still points to the old place

    assert restart_and_replay(database, library_dir) == 1

    assert (library_dir / NEW_PATH).read_bytes() == CONTENT
    assert stored_path(database, image_id) == str(NEW_PATH)
    assert journal(database) == []
    assert not (library_dir / "photo" / "_unknown").exists()


def test_crash_while_copying_across_filesystems(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_copy_across_filesystems(monkeypatch)
    monkeypatch.setattr(_files.os, "replace", crash)  # the copy is written but not yet complete
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)
    assert _files.partial_path(library_dir / NEW_PATH).exists()
    monkeypatch.undo()

    assert restart_and_replay(database, library_dir) == 1

    assert not _files.partial_path(library_dir / NEW_PATH).exists()
    assert (library_dir / OLD_PATH).read_bytes() == CONTENT
    assert stored_path(database, image_id) == str(OLD_PATH)
    assert journal(database) == []


def test_crash_after_copying_before_deleting_the_original(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    force_copy_across_filesystems(monkeypatch)
    monkeypatch.setattr(_files, "delete_file", crash)
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)
    assert (library_dir / OLD_PATH).exists() and (library_dir / NEW_PATH).exists()
    monkeypatch.undo()

    assert restart_and_replay(database, library_dir) == 1

    assert not (library_dir / OLD_PATH).exists()
    assert (library_dir / NEW_PATH).read_bytes() == CONTENT
    assert stored_path(database, image_id) == str(NEW_PATH)
    assert journal(database) == []


def test_crash_before_removing_empty_folders(
    storage: StorageService, database: Database, library_dir: Path, image_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_service, "remove_empty_folders", crash)
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)

    assert restart_and_replay(database, library_dir) == 0  # nothing left to finish

    assert stored_path(database, image_id) == str(NEW_PATH)
    assert (library_dir / NEW_PATH).read_bytes() == CONTENT
    assert journal(database) == []


def test_file_found_nowhere_keeps_its_journal_entry(
    storage: StorageService,
    database: Database,
    library_dir: Path,
    image_id: int,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(_service, "move_file", crash)
    with pytest.raises(SimulatedCrash):
        storage.move_image_file(image_id, NEW_PATH)
    os.remove(library_dir / OLD_PATH)

    with caplog.at_level(logging.ERROR):
        assert restart_and_replay(database, library_dir) == 0

    assert journal(database) == [(str(OLD_PATH), str(NEW_PATH))]
    assert "neither at" in caplog.text
