# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Shared test fixtures: every test gets its own data folder, never the user's real one."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pictorio_db.app import create_app
from pictorio_db.config import DEFAULT_HOST, DEFAULT_PORT, Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(host=DEFAULT_HOST, port=DEFAULT_PORT, data_dir=tmp_path)


@pytest.fixture
def client(config: Config) -> Iterator[TestClient]:
    with TestClient(create_app(config)) as started_client:  # starts the app, which opens the database
        yield started_client
