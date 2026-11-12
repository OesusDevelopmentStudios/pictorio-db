# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest
from fastapi.testclient import TestClient

from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    client.app.state.auth.create_user("kid", PASSWORD, Role.USER)
    response = client.post("/api/v1/auth/tokens", json={"username": "kid", "password": PASSWORD, "device_name": "t"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_tags_need_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/tags").status_code == 401


def test_returns_items_with_tag_and_count(client: TestClient, user_headers: dict[str, str]) -> None:
    with client.app.state.database.engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO tag (namespace_id, name) SELECT id, 'summer' FROM namespace WHERE name = 'general'"
        )

    response = client.get("/api/v1/tags", params={"prefix": "sum"}, headers=user_headers)

    assert response.status_code == 200
    assert response.json() == {"items": [{"tag": "general:summer", "image_count": 0}]}


@pytest.mark.parametrize("limit", [0, 101])
def test_limit_must_be_between_1_and_100(client: TestClient, user_headers: dict[str, str], limit: int) -> None:
    response = client.get("/api/v1/tags", params={"limit": limit}, headers=user_headers)

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "query.limit"
