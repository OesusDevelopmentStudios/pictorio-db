# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""File operations that survive a crash or power cut: a file is either at its old place or complete at
its new one."""

import errno
import os
import shutil
from pathlib import Path

PARTIAL_SUFFIX = ".partial"  # a copy that is still being written


def move_file(source: Path, target: Path) -> None:
    """Never overwrites: raises FileExistsError if the target exists."""
    if target.exists():
        raise FileExistsError(errno.EEXIST, "The target file exists already", str(target))

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise

        copy_across_filesystems(source, target)
        return

    # The new folder entries must reach the disk too, not only the file's data.
    sync_folder(target.parent)
    sync_folder(source.parent)


def copy_across_filesystems(source: Path, target: Path) -> None:
    """rename() cannot cross filesystems. The copy gets its final name only when it is complete, so a file
    at the target is always whole; the original is deleted last."""
    partial = partial_path(target)
    with source.open("rb") as source_file, partial.open("wb") as partial_file:
        shutil.copyfileobj(source_file, partial_file)
        partial_file.flush()
        os.fsync(partial_file.fileno())

    os.replace(partial, target)
    sync_folder(target.parent)
    delete_file(source)


def delete_file(path: Path) -> None:
    path.unlink()
    sync_folder(path.parent)


def partial_path(target: Path) -> Path:
    return target.with_name(target.name + PARTIAL_SUFFIX)


def sync_folder(folder: Path) -> None:
    folder_descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(folder_descriptor)
    finally:
        os.close(folder_descriptor)


def remove_empty_folders(folder: Path, library_dir: Path) -> None:
    """Removes `folder` and its parents while they are empty, but never the library folder itself."""
    while folder != library_dir and folder.is_relative_to(library_dir):
        try:
            folder.rmdir()
        except OSError:
            return  # not empty

        folder = folder.parent
