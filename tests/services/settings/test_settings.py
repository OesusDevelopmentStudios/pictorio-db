# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pictorio_db.db import Database
from pictorio_db.services.settings import SettingsService


def test_unchanged_setting_is_none(database: Database) -> None:
    assert SettingsService(database).get("path_template") is None


def test_keeps_values_and_replaces_them(database: Database) -> None:
    settings = SettingsService(database)

    settings.set("path_template", "{category}/{year}")
    settings.set("path_template", "{year}")

    assert settings.get("path_template") == "{year}"


def test_keeps_json_values(database: Database) -> None:
    settings = SettingsService(database)

    settings.set("rating_values", ["sfw", "nsfw"])
    settings.set("limits", {"max_upload_bytes": 209715200})

    assert settings.get("rating_values") == ["sfw", "nsfw"]
    assert settings.get("limits") == {"max_upload_bytes": 209715200}
