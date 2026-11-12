# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Server settings that the admin can change, kept in the database. Each owner of a setting (e.g. the
storage service for the path template) knows its key, default and rules; this store only keeps values."""

from typing import Any

from pictorio_db.db import Database
from pictorio_db.db.models import Setting


class SettingsService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get(self, key: str) -> Any | None:
        """None if the setting was never changed, so the owner uses its default."""
        with self._database.session() as session:
            setting = session.get(Setting, key)
            return None if setting is None else setting.value

    def set(self, key: str, value: Any) -> None:
        with self._database.session() as session:
            session.merge(Setting(key=key, value=value))
            session.commit()


__all__ = ["SettingsService"]
