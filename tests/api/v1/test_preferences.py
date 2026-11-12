# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    client.app.state.auth.create_user("kid", PASSWORD, Role.USER)
    login = {"username": "kid", "password": PASSWORD, "device_name": "t"}
    return {"Authorization": f"Bearer {client.post('/api/v1/auth/tokens', json=login).json()['token']}"}


def upload(client: TestClient, headers: dict[str, str], colour: str, tags: list[str]) -> int:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="JPEG")
    metadata = json.dumps({"original_filename": f"{colour}.jpg", "tags": tags})
    response = client.post(
        "/api/v1/images", headers=headers, files={"file": ("a.jpg", buffer.getvalue())}, data={"metadata": metadata}
    )
    return response.json()["id"]


def test_preferences_need_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/preferences").status_code == 401
    assert client.put("/api/v1/preferences", json={"hidden_filters": []}).status_code == 401


def test_stores_and_returns_hidden_filters(client: TestClient, headers: dict[str, str]) -> None:
    assert client.get("/api/v1/preferences", headers=headers).json() == {"hidden_filters": []}

    response = client.put("/api/v1/preferences", json={"hidden_filters": ["rating:nsfw"]}, headers=headers)

    assert response.status_code == 200
    assert client.get("/api/v1/preferences", headers=headers).json() == {"hidden_filters": ["rating:nsfw"]}


def test_invalid_filter_is_named(client: TestClient, headers: dict[str, str]) -> None:
    response = client.put("/api/v1/preferences", json={"hidden_filters": ["rating:sfw", "(a"]}, headers=headers)

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.hidden_filters.1"


def test_search_hides_filtered_images_by_default(client: TestClient, headers: dict[str, str]) -> None:
    safe = upload(client, headers, "green", ["rating:sfw"])
    hidden = upload(client, headers, "red", ["rating:nsfw"])
    client.put("/api/v1/preferences", json={"hidden_filters": ["rating:nsfw"]}, headers=headers)

    def found(params: dict[str, object]) -> tuple[set[int], str]:
        body = client.get("/api/v1/images", params=params, headers=headers).json()
        return {item["id"] for item in body["items"]}, body["effective_query"]

    assert found({}) == ({safe}, "-rating:nsfw")
    assert found({"apply_hidden_filters": False}) == ({safe, hidden}, "")
    assert found({"q": "rating:nsfw"}) == ({hidden}, "rating:nsfw")
