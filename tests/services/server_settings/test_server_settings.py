# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

import pytest

from pictorio_db.db import Database
from pictorio_db.services.images import ImagesService
from pictorio_db.services.importer import DEFAULT_MAX_UPLOAD_BYTES, ImporterService
from pictorio_db.services.jobs import JobKind, JobsService, JobStatus, Relayout
from pictorio_db.services.server_settings import ServerSettings, ServerSettingsInfo, SettingsChanges
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

DEFAULTS = ServerSettingsInfo(
    path_template="{category}/{author}/{year}",
    max_upload_bytes=DEFAULT_MAX_UPLOAD_BYTES,
    rating_values=["sfw", "nsfw"],
    library_dir=Path("/srv/library"),
    import_dir=Path("/srv/import"),
)


@pytest.fixture
def server_settings(database: Database, tmp_path: Path) -> ServerSettings:
    """The worker is not started: relayout jobs stay queued."""
    settings = SettingsService(database)
    tags = TagsService(database, lambda: storage.path_template_namespaces())
    storage = StorageService(database, settings, Path("/srv/library"), tags.namespace_names)
    images = ImagesService(database, tags, storage)
    importer = ImporterService(images, tags, storage, ThumbnailsService(tmp_path / "thumbnails"), settings)
    return ServerSettings(storage, importer, tags, Relayout(JobsService(database), images), Path("/srv/import"))


def test_shows_the_defaults(server_settings: ServerSettings) -> None:
    assert server_settings.current() == DEFAULTS


def test_changes_the_given_settings_only(server_settings: ServerSettings) -> None:
    settings, job = server_settings.change(SettingsChanges(max_upload_bytes=50_000_000, rating_values=["Safe"]), None)

    assert (settings.max_upload_bytes, settings.rating_values) == (50_000_000, ["safe"])
    assert settings.path_template == DEFAULTS.path_template
    assert job is None
    assert server_settings.current() == settings


def test_new_path_template_starts_a_relayout(server_settings: ServerSettings) -> None:
    settings, job = server_settings.change(SettingsChanges(path_template=" {year}/{category} "), user_id=None)

    assert settings.path_template == "{year}/{category}"
    assert job is not None and (job.kind, job.status) == (JobKind.RELAYOUT, JobStatus.QUEUED)


def test_same_path_template_moves_nothing(server_settings: ServerSettings) -> None:
    assert server_settings.change(SettingsChanges(path_template=DEFAULTS.path_template), None)[1] is None


@pytest.mark.parametrize(
    "changes",
    [
        SettingsChanges(path_template="{nonsense}", max_upload_bytes=50_000_000, rating_values=["safe"]),
        SettingsChanges(path_template="{year}", max_upload_bytes=1, rating_values=["safe"]),
        SettingsChanges(path_template="{year}", max_upload_bytes=50_000_000, rating_values=[]),
    ],
    ids=["template", "upload limit", "ratings"],
)
def test_one_invalid_setting_changes_nothing(server_settings: ServerSettings, changes: SettingsChanges) -> None:
    with pytest.raises(Problem) as raised:
        server_settings.change(changes, None)

    assert raised.value.status == 422
    assert server_settings.current() == DEFAULTS
