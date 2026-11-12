# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from fastapi.testclient import TestClient
from sqlalchemy import select

from pictorio_db.app import create_app
from pictorio_db.config import Config
from pictorio_db.db import DATABASE_FILE_NAME
from pictorio_db.db.models import Namespace


def test_creating_the_app_touches_no_files(config: Config) -> None:
    create_app(config)

    assert not (config.data_dir / DATABASE_FILE_NAME).exists()


def test_starting_creates_the_database(config: Config) -> None:
    with TestClient(create_app(config)) as client:
        with client.app.state.database.session() as session:
            namespace_names = session.scalars(select(Namespace.name)).all()

    assert (config.data_dir / DATABASE_FILE_NAME).exists()
    assert "general" in namespace_names
