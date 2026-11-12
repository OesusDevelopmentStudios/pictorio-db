# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import errno
import logging
import os
import shutil
import uuid
from collections import defaultdict
from collections.abc import Callable, Collection
from datetime import datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select, update

from pictorio_db.db import Database
from pictorio_db.db.models import FileMove, Image
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage._files import delete_file, move_file, partial_path, remove_empty_folders
from pictorio_db.services.storage._paths import (
    DEFAULT_PATH_TEMPLATE,
    PathTemplate,
    folder_path,
    parse_path_template,
)
from pictorio_db.services.tags import TagName
from pictorio_db.utils.time import utc_now

PATH_TEMPLATE_SETTING = "path_template"
INCOMING_FOLDER = ".incoming"

_logger = logging.getLogger(__name__)


class StorageService:
    """The library folder and its layout. `namespace_names` returns the namespaces that exist, which the
    path template may use."""

    def __init__(
        self,
        database: Database,
        settings: SettingsService,
        library_dir: Path,
        namespace_names: Callable[[], Collection[str]],
    ) -> None:
        self._database = database
        self._settings = settings
        self._namespace_names = namespace_names
        self.library_dir = library_dir

    # --- Path template

    def path_template(self) -> PathTemplate:
        stored_text = self._settings.get(PATH_TEMPLATE_SETTING)
        text = DEFAULT_PATH_TEMPLATE if stored_text is None else stored_text
        return parse_path_template(text, self._namespace_names())

    def path_template_namespaces(self) -> frozenset[str]:
        return self.path_template().namespaces

    def checked_path_template(self, text: str) -> PathTemplate:
        """Raises 422 validation_error, e.g. for an unknown placeholder."""
        return parse_path_template(text.strip(), self._namespace_names())

    def set_path_template(self, text: str) -> PathTemplate:
        """Checks and stores the template; files are not moved. Raises 422 validation_error; the stored one then
        stays."""
        template = self.checked_path_template(text)
        self._settings.set(PATH_TEMPLATE_SETTING, template.text)
        return template

    # --- Where images belong

    def path_for(self, tags: list[TagName], taken_at: datetime, file_name: str) -> PurePosixPath:
        """The place in the library that the path template gives an image with these tags."""
        tags_by_namespace: defaultdict[str, list[str]] = defaultdict(list)
        for tag in tags:
            tags_by_namespace[tag.namespace].append(tag.name)

        return folder_path(self.path_template(), tags_by_namespace, taken_at) / file_name

    def move_to_layout(
        self, image_id: int, current_path: PurePosixPath, tags: list[TagName], taken_at: datetime
    ) -> PurePosixPath:
        """Moves an image's file to where its tags now place it, keeping the file name, and returns the place.
        Raises OSError if moving fails; the file then stays where the database says it is."""
        wanted_path = self.path_for(tags, taken_at, current_path.name)
        if wanted_path.parent == current_path.parent:
            return current_path

        new_path = self._free_library_path(wanted_path)
        self.move_image_file(image_id, new_path)
        return new_path

    # --- New files

    def new_incoming_path(self) -> Path:
        """A new, unused file name for an upload to arrive in."""
        incoming_dir = self.library_dir / INCOMING_FOLDER
        incoming_dir.mkdir(parents=True, exist_ok=True)
        return incoming_dir / f"{uuid.uuid4().hex}.upload"

    def store_incoming(self, incoming: Path, library_path: PurePosixPath) -> PurePosixPath:
        """Moves a complete upload to its place in the library and returns that place. Another file with the
        same name (practically impossible, as names contain the SHA-256) gets a number added: name_2.jpg."""
        with incoming.open("rb") as incoming_file:
            os.fsync(incoming_file.fileno())  # the data is on the disk before the file appears in the library

        stored_path = self._free_library_path(library_path)
        move_file(incoming, self.absolute_path(stored_path))
        return stored_path

    def delete_library_file(self, library_path: PurePosixPath | str) -> None:
        file_path = self.absolute_path(library_path)
        file_path.unlink(missing_ok=True)
        remove_empty_folders(file_path.parent, self.library_dir)

    def clean_incoming(self) -> None:
        """Run at startup: removes uploads that were interrupted."""
        shutil.rmtree(self.library_dir / INCOMING_FOLDER, ignore_errors=True)

    def _free_library_path(self, library_path: PurePosixPath) -> PurePosixPath:
        candidate = library_path
        number = 1
        while self.absolute_path(candidate).exists():
            number += 1
            candidate = library_path.with_stem(f"{library_path.stem}_{number}")

        return candidate

    # --- Moving files

    def move_image_file(self, image_id: int, to_path: PurePosixPath) -> None:
        """Moves an image's file within the library, e.g. after a tag change. `to_path` is relative to the
        library. Raises FileExistsError if a file is in the way, or another OSError if moving fails."""
        target = self.absolute_path(to_path)
        if target.exists():
            raise FileExistsError(errno.EEXIST, "The target file exists already", str(target))

        move_id, from_path = self._record_move(image_id, to_path)
        try:
            move_file(self.absolute_path(from_path), target)
        except OSError:
            if not target.exists():  # nothing reached the new place: the move did not happen
                partial_path(target).unlink(missing_ok=True)
                self._forget_move(move_id)

            raise  # otherwise the complete copy is there; the next start finishes the move

        self._finish_move(move_id, image_id, to_path)
        remove_empty_folders(self.absolute_path(from_path).parent, self.library_dir)

    def finish_interrupted_moves(self) -> int:
        """Run at startup: completes or undoes the moves a crash interrupted. Returns how many it handled."""
        with self._database.session() as session:
            moves = session.scalars(select(FileMove).order_by(FileMove.id)).all()

        return sum(self._finish_interrupted_move(move) for move in moves)

    def absolute_path(self, library_path: PurePosixPath | str) -> Path:
        relative = PurePosixPath(library_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Not a path inside the library: {library_path}")

        return self.library_dir / relative

    # The steps of a move. A crash can happen between any two of them.

    def _record_move(self, image_id: int, to_path: PurePosixPath) -> tuple[int, PurePosixPath]:
        with self._database.session() as session:
            from_path = session.get_one(Image, image_id).storage_path
            move = FileMove(image_id=image_id, from_path=from_path, to_path=str(to_path), created_at=utc_now())
            session.add(move)
            session.commit()
            return move.id, PurePosixPath(from_path)

    def _finish_move(self, move_id: int, image_id: int, to_path: PurePosixPath | str) -> None:
        """The new path and the end of the move are recorded in one transaction."""
        with self._database.session() as session:
            session.execute(
                update(Image).where(Image.id == image_id).values(storage_path=str(to_path), updated_at=utc_now())
            )
            session.execute(delete(FileMove).where(FileMove.id == move_id))
            session.commit()

    def _forget_move(self, move_id: int) -> None:
        with self._database.session() as session:
            session.execute(delete(FileMove).where(FileMove.id == move_id))
            session.commit()

    def _finish_interrupted_move(self, move: FileMove) -> bool:
        source = self.absolute_path(move.from_path)
        target = self.absolute_path(move.to_path)
        if target.exists():
            if source.exists():
                delete_file(source)  # the copy across filesystems was complete; only the original was left

            self._finish_move(move.id, move.image_id, move.to_path)
            remove_empty_folders(source.parent, self.library_dir)
            _logger.info("Finished an interrupted move of image %s to %s", move.image_id, move.to_path)
            return True

        if source.exists():
            partial_path(target).unlink(missing_ok=True)  # the copy had not finished; the original is intact
            self._forget_move(move.id)
            _logger.info("Undid an interrupted move of image %s; it stays at %s", move.image_id, move.from_path)
            return True

        _logger.error(
            "The file of image %s is neither at %s nor at %s; the move is kept for an admin to look at",
            move.image_id,
            move.from_path,
            move.to_path,
        )
        return False
