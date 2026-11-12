# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from fastapi.testclient import TestClient

import pictorio_db
from pictorio_db.services.auth import Role


def test_server_info_is_public_and_names_the_server(client: TestClient) -> None:
    response = client.get("/api/v1/server/info")

    assert response.status_code == 200
    assert response.json() == {
        "name": "pictorio-db",
        "version": pictorio_db.__version__,
        "api_version": 1,
        "setup_required": True,
    }


def test_setup_is_no_longer_required_once_an_admin_exists(client: TestClient) -> None:
    client.app.state.auth.create_user("apo", "correct horse battery", Role.ADMIN)

    response = client.get("/api/v1/server/info")

    assert response.json()["setup_required"] is False
