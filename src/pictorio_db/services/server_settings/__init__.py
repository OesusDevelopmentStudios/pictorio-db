# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The server's settings as the admin sees them: the API and the web admin pages read and change them here."""

from dataclasses import dataclass
from pathlib import Path

from pictorio_db.services.importer import ImporterService, check_upload_limit
from pictorio_db.services.jobs import JobInfo, Relayout
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService


@dataclass(frozen=True)
class ServerSettingsInfo:
    path_template: str
    max_upload_bytes: int
    rating_values: list[str]
    library_dir: Path  # from the environment; read-only here
    import_dir: Path | None


@dataclass(frozen=True)
class SettingsChanges:
    """None leaves a setting as it is."""

    path_template: str | None = None
    max_upload_bytes: int | None = None
    rating_values: list[str] | None = None


class ServerSettings:
    def __init__(
        self,
        storage: StorageService,
        importer: ImporterService,
        tags: TagsService,
        relayout: Relayout,
        import_dir: Path | None,
    ) -> None:
        self._storage = storage
        self._importer = importer
        self._tags = tags
        self._relayout = relayout
        self._import_dir = import_dir

    def current(self) -> ServerSettingsInfo:
        return ServerSettingsInfo(
            path_template=self._storage.path_template().text,
            max_upload_bytes=self._importer.max_upload_bytes(),
            rating_values=self._tags.rating_values(),
            library_dir=self._storage.library_dir,
            import_dir=self._import_dir,
        )

    def change(self, changes: SettingsChanges, user_id: int | None) -> tuple[ServerSettingsInfo, JobInfo | None]:
        """All or nothing: every value is checked before any is stored. A different path template starts a
        relayout job, which is returned. Raises 422 validation_error or invalid_tag."""
        template = None
        if changes.path_template is not None:
            template = self._storage.checked_path_template(changes.path_template)

        rating_values = None
        if changes.rating_values is not None:
            rating_values = self._tags.checked_rating_values(changes.rating_values)

        if changes.max_upload_bytes is not None:
            check_upload_limit(changes.max_upload_bytes)

        # Everything is valid: store it.
        if changes.max_upload_bytes is not None:
            self._importer.set_max_upload_bytes(changes.max_upload_bytes)

        if rating_values is not None:
            self._tags.set_rating_values(rating_values)

        relayout_job = None
        if template is not None and template.text != self._storage.path_template().text:
            self._storage.set_path_template(template.text)
            relayout_job = self._relayout.start(user_id)

        return self.current(), relayout_job


__all__ = ["ServerSettings", "ServerSettingsInfo", "SettingsChanges"]
