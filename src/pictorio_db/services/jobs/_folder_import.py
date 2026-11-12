# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pictorio_db.services.access import Restrictions
from pictorio_db.services.importer import ImporterService, UploadMetadata
from pictorio_db.services.jobs._service import JobContext, JobInfo, JobKind, JobsService
from pictorio_db.services.tags import TagsService
from pictorio_db.utils.problems import Problem

NO_RESTRICTIONS = Restrictions([])  # only admins start folder imports

_logger = logging.getLogger(__name__)


@dataclass
class _Counts:
    imported: int = 0
    duplicates: int = 0
    unsupported: int = 0
    failed: list[dict[str, str]] = field(default_factory=list)  # {path, code}; path relative to the import folder

    def fail(self, path: str, code: str) -> None:
        self.failed.append({"path": path, "code": code})


class FolderImport:
    """Imports every file in a folder on the server, e.g. a NAS share mounted at PICTORIO_IMPORT_DIR. Only
    folders inside that one can be imported, so the API cannot read other files on the server."""

    def __init__(
        self, jobs: JobsService, importer: ImporterService, tags: TagsService, import_dir: Path | None
    ) -> None:
        self._jobs = jobs
        self._importer = importer
        self._tags = tags
        self._import_dir = import_dir

    def start(self, source_subdir: str, remove_originals: bool, tags: list[str], user_id: int) -> JobInfo:
        """Checks what can be checked now, so that mistakes are answered at once rather than by a failed job."""
        folder = self._source_folder(source_subdir)
        self._tags.resolve_tags(tags)
        if remove_originals and not os.access(folder, os.W_OK):
            raise Problem(
                422,
                "validation_error",
                "Folder is read-only",
                "The originals cannot be removed. Make the folder writable, or import without removing them.",
            )

        params = {"source_subdir": source_subdir, "remove_originals": remove_originals, "tags": tags}
        return self._jobs.submit(JobKind.FOLDER_IMPORT, params, user_id)

    def run(self, context: JobContext) -> dict[str, Any]:
        """The job. Run again after a restart, the files imported before count as duplicates."""
        source_subdir = context.params["source_subdir"]
        folder = self._source_folder(source_subdir)
        files = sorted(_files_in(folder))
        counts = _Counts()
        context.report_progress(0, len(files))
        for done, path in enumerate(files, start=1):
            shown_path = (PurePosixPath(source_subdir) / path.relative_to(folder)).as_posix()
            self._import_file(path, shown_path, context, counts)
            context.report_progress(done, len(files))  # stops here if the server is stopping

        return {
            "imported": counts.imported,
            "duplicates": counts.duplicates,
            "unsupported": counts.unsupported,
            "failed": counts.failed,
        }

    def _import_file(self, path: Path, shown_path: str, context: JobContext, counts: _Counts) -> None:
        if path.is_symlink() or not path.is_file():
            counts.fail(shown_path, "not_a_regular_file")
            return

        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            metadata = UploadMetadata(path.name, file_mtime=mtime, tags=tuple(context.params["tags"]))
            self._importer.import_copy(path, metadata, context.created_by, NO_RESTRICTIONS)
            counts.imported += 1
        except Problem as problem:
            if problem.code == "unsupported_media_type":
                counts.unsupported += 1
                return

            if problem.code != "duplicate_image":
                counts.fail(shown_path, problem.code)
                return

            counts.duplicates += 1  # the library has the file, so it may be removed too
        except Exception:
            _logger.exception("Could not import %s", path)
            counts.fail(shown_path, "internal_error")
            return

        if context.params["remove_originals"]:
            try:
                path.unlink()
            except OSError as error:
                _logger.warning("Could not remove the imported original %s: %s", path, error)
                counts.fail(shown_path, "not_removed")

    def _source_folder(self, source_subdir: str) -> Path:
        if self._import_dir is None:
            raise Problem(
                409,
                "import_dir_not_set",
                "Folder imports are off",
                "Set PICTORIO_IMPORT_DIR on the server to the folder to import from.",
            )

        relative = PurePosixPath(source_subdir)
        import_dir = self._import_dir.resolve()
        folder = (import_dir / relative).resolve()
        # resolve() follows symbolic links, so a link that leads outside is caught too
        if relative.is_absolute() or ".." in relative.parts or not folder.is_relative_to(import_dir):
            raise Problem(
                422,
                "validation_error",
                "Invalid folder",
                "source_subdir must be a folder inside the import folder, without '..'.",
            )

        if not folder.is_dir():
            raise Problem(422, "validation_error", "Folder not found", f"The import folder has no {source_subdir!r}.")

        return folder


def _files_in(folder: Path) -> Iterator[Path]:
    """Everything in the folder and its subfolders except the folders. Links to folders are not followed."""
    with os.scandir(folder) as listing:
        entries = list(listing)

    for entry in entries:
        if entry.is_dir(follow_symlinks=False):
            yield from _files_in(Path(entry.path))
        else:
            yield Path(entry.path)
