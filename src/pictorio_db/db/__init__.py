# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The SQLite database: opening it, bringing its schema up to date, and sessions."""

from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from pictorio_db.db._connection import create_sqlite_engine
from pictorio_db.db._migrations import upgrade_to_latest_schema

DATABASE_FILE_NAME = "pictorio.sqlite3"


class Database:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(engine)

    def session(self) -> Session:
        return self._session_factory()

    def close(self) -> None:
        self.engine.dispose()


def open_database(database_path: Path) -> Database:
    """Opens the database, creating it or upgrading its schema first if needed."""
    engine = create_sqlite_engine(database_path)
    upgrade_to_latest_schema(engine)
    return Database(engine)
