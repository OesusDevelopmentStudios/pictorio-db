# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath

from pictorio_db.services.access import Restrictions
from pictorio_db.services.images import ImageRecord, ImagesService, NewImage, duplicate_image
from pictorio_db.services.importer._inspection import ImageFacts, file_sha256, inspect_image
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService, file_name
from pictorio_db.services.tags import TagName, TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

MAX_UPLOAD_BYTES_SETTING = "max_upload_bytes"
DEFAULT_MAX_UPLOAD_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class UploadMetadata:
    original_filename: str
    file_mtime: datetime | None = None  # the original file's modification time, as the client saw it
    client_sha256: str | None = None  # what the client computed, to detect damage on the way
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TakenAt:
    time: datetime  # local wall-clock time
    source: str  # "exif", "file_mtime" or "import_time"
    utc_offset_minutes: int | None


def local_now() -> datetime:
    """The server's local wall-clock time, the way a photo's own date is recorded."""
    return datetime.now().replace(microsecond=0)


class ImporterService:
    """Brings an uploaded file into the library: checks it, stores it in its place, records it with its tags
    and makes its thumbnails."""

    def __init__(
        self,
        images: ImagesService,
        tags: TagsService,
        storage: StorageService,
        thumbnails: ThumbnailsService,
        settings: SettingsService,
        now: Callable[[], datetime] = local_now,
    ) -> None:
        self._images = images
        self._tags = tags
        self._storage = storage
        self._thumbnails = thumbnails
        self._settings = settings
        self._now = now

    def max_upload_bytes(self) -> int:
        stored_limit = self._settings.get(MAX_UPLOAD_BYTES_SETTING)
        return DEFAULT_MAX_UPLOAD_BYTES if stored_limit is None else stored_limit

    def new_incoming_path(self) -> Path:
        """Where to write an upload before passing it to import_image()."""
        return self._storage.new_incoming_path()

    def import_image(
        self, incoming: Path, metadata: UploadMetadata, user_id: int | None, restrictions: Restrictions
    ) -> ImageRecord:
        """Takes over `incoming`: it ends up in the library or is deleted. Raises 409 duplicate_image,
        403 tag_restricted, 415 unsupported_media_type, 422 checksum_mismatch or 422 invalid_tag; nothing is
        stored then."""
        sha256, tags, facts, taken_at = self._checked_upload(incoming, metadata, restrictions)
        library_path = self._storage.path_for(
            tags, taken_at.time, file_name(metadata.original_filename, sha256, facts.type.extension)
        )
        stored_path = self._storage.store_incoming(incoming, library_path)
        new_image = self._new_image(metadata, sha256, facts, taken_at, stored_path, user_id)
        try:
            return self._images.create_image(new_image, tags)
        except Exception:
            self._storage.delete_library_file(stored_path)
            if self._images.find_id_by_sha256(sha256) is None:  # not another upload of the same file
                self._thumbnails.delete_thumbnails(sha256)

            raise

    def import_copy(
        self, source: Path, metadata: UploadMetadata, user_id: int | None, restrictions: Restrictions
    ) -> ImageRecord:
        """Imports a copy of `source` and leaves the file itself alone. Raises like import_image()."""
        sha256 = file_sha256(source)
        self._check_not_duplicate(sha256, restrictions)  # before copying: a repeated import is mostly duplicates
        incoming = self.new_incoming_path()
        try:
            shutil.copyfile(source, incoming)
        except Exception:
            incoming.unlink(missing_ok=True)
            raise

        # The checksum finds a source that changed while it was copied.
        return self.import_image(incoming, replace(metadata, client_sha256=sha256), user_id, restrictions)

    def _checked_upload(
        self, incoming: Path, metadata: UploadMetadata, restrictions: Restrictions
    ) -> tuple[str, list[TagName], ImageFacts, TakenAt]:
        """Everything that can refuse an upload, before anything is stored."""
        try:
            sha256 = file_sha256(incoming)
            _check_client_sha256(metadata.client_sha256, sha256)
            self._check_not_duplicate(sha256, restrictions)
            tags = self._tags.resolve_tags(list(metadata.tags))
            facts = inspect_image(incoming)
            taken_at = self._taken_at(metadata, facts)
            restrictions.check_tags_allowed(tags, taken_at.time)
        except Exception:
            incoming.unlink(missing_ok=True)
            raise

        try:
            self._thumbnails.create_thumbnails(incoming, sha256)  # decodes the whole image: finds damaged data
        except Exception:
            incoming.unlink(missing_ok=True)
            self._thumbnails.delete_thumbnails(sha256)
            raise

        return sha256, tags, facts, taken_at

    def _check_not_duplicate(self, sha256: str, restrictions: Restrictions) -> None:
        existing_image_id = self._images.find_id_by_sha256(sha256)
        if existing_image_id is not None:
            # The user has the file already; confirming a copy exists reveals little, but not which image.
            visible = self._images.is_visible(existing_image_id, restrictions)
            raise duplicate_image(sha256, existing_image_id if visible else None)

    def _new_image(
        self,
        metadata: UploadMetadata,
        sha256: str,
        facts: ImageFacts,
        taken_at: TakenAt,
        stored_path: PurePosixPath,
        user_id: int | None,
    ) -> NewImage:
        return NewImage(
            sha256=sha256,
            storage_path=str(stored_path),
            original_filename=metadata.original_filename,
            mime_type=facts.type.mime_type,
            width=facts.width,
            height=facts.height,
            file_size=self._storage.absolute_path(stored_path).stat().st_size,
            taken_at=taken_at.time,
            taken_at_source=taken_at.source,
            taken_at_utc_offset_minutes=taken_at.utc_offset_minutes,
            imported_by_user_id=user_id,
        )

    def _taken_at(self, metadata: UploadMetadata, facts: ImageFacts) -> TakenAt:
        """From EXIF; else the original file's modification time; else now. The source is recorded too."""
        if facts.taken_at is not None:
            return TakenAt(facts.taken_at, "exif", facts.taken_at_utc_offset_minutes)

        if metadata.file_mtime is not None:
            return TakenAt(metadata.file_mtime.replace(tzinfo=None), "file_mtime", None)

        return TakenAt(self._now(), "import_time", None)


def _check_client_sha256(client_sha256: str | None, sha256: str) -> None:
    if client_sha256 is not None and client_sha256.lower() != sha256:
        raise Problem(
            422,
            "checksum_mismatch",
            "File damaged on the way",
            "The file's SHA-256 differs from client_sha256; send it again.",
        )
