# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pictorio_db.app import create_app
from pictorio_db.config import Config
from pictorio_db.db import DATABASE_FILE_NAME
from pictorio_db.db.models import Namespace
from pictorio_db.services.auth import Role


def test_creating_the_app_touches_no_files(config: Config) -> None:
    create_app(config)

    assert not (config.data_dir / DATABASE_FILE_NAME).exists()


def test_starting_creates_the_database(config: Config) -> None:
    with TestClient(create_app(config)) as client:
        with client.app.state.database.session() as session:
            namespace_names = session.scalars(select(Namespace.name)).all()

    assert (config.data_dir / DATABASE_FILE_NAME).exists()
    assert "general" in namespace_names


def test_errors_are_problem_details(client: TestClient) -> None:
    response = client.get("/api/v1/no-such-endpoint")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_found"


def test_logs_the_setup_code_while_no_admin_exists(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING), TestClient(create_app(config)) as client:
        setup_code = client.app.state.auth.setup_code()

    assert setup_code in caplog.text
    assert "/admin/setup" in caplog.text


def test_does_not_log_a_setup_code_once_an_admin_exists(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    with TestClient(create_app(config)) as client:
        client.app.state.auth.create_user("apo", "correct horse battery", Role.ADMIN)
    caplog.clear()  # the first start had no admin yet and rightly logged a code

    with caplog.at_level(logging.WARNING), TestClient(create_app(config)):
        pass

    assert "setup code" not in caplog.text
