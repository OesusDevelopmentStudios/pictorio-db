# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path
from sqlite3 import Connection as SqliteConnection
from typing import Any

from sqlalchemy import Engine, create_engine, event

BUSY_TIMEOUT_MILLISECONDS = 5000


def create_sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path}")
    event.listen(engine, "connect", _configure_connection)
    return engine


def _configure_connection(connection: SqliteConnection, _connection_record: Any) -> None:
    cursor = connection.cursor()
    # Readers do not block the writer and the other way round; the setting is stored in the file.
    cursor.execute("PRAGMA journal_mode = WAL")
    # SQLite ignores foreign keys unless every connection turns them on.
    cursor.execute("PRAGMA foreign_keys = ON")
    # Wait for a short write by another connection instead of failing at once.
    cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MILLISECONDS}")
    cursor.close()
