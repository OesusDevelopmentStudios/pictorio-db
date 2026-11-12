# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


# --- Renaming and deleting, for admins

@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    client.app.state.auth.create_user("apo", PASSWORD, Role.ADMIN)
    response = client.post("/api/v1/auth/tokens", json={"username": "apo", "password": PASSWORD, "device_name": "t"})
    return {"Authorization": f"Bearer {response.json()['token']}"}


def upload(client: TestClient, headers: dict[str, str], tags: list[str]) -> int:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "teal").save(buffer, format="JPEG")
    metadata = json.dumps({"original_filename": "beach.jpg", "tags": tags})
    files = {"file": ("beach.jpg", buffer.getvalue())}
    return client.post("/api/v1/images", headers=headers, files=files, data={"metadata": metadata}).json()["id"]


def test_admin_renames_a_folder_tag(client: TestClient, admin_headers: dict[str, str]) -> None:
    image_id = upload(client, admin_headers, ["author:anon_one"])

    response = client.patch("/api/v1/tags/author/anon_one", json={"new_tag": "Author:Anon Two"}, headers=admin_headers)

    assert (response.status_code, response.json()["tag"]) == (200, "author:anon_two")
    job_id = response.json()["job_id"]
    deadline = time.monotonic() + 5
    while client.get(f"/api/v1/jobs/{job_id}", headers=admin_headers).json()["status"] != "done":
        assert time.monotonic() < deadline, "the relayout did not finish in time"
        time.sleep(0.01)

    image = client.get(f"/api/v1/images/{image_id}", headers=admin_headers).json()
    assert image["tags"] == ["author:anon_two"]
    assert "/anon_two/" in image["storage_path"]


def test_admin_deletes_a_tag(client: TestClient, admin_headers: dict[str, str]) -> None:
    image_id = upload(client, admin_headers, ["summer", "beach"])

    response = client.delete("/api/v1/tags/general/summer", headers=admin_headers)

    assert response.json() == {"job_id": None}
    assert client.get(f"/api/v1/images/{image_id}", headers=admin_headers).json()["tags"] == ["general:beach"]


def test_unknown_tag_is_not_found(client: TestClient, admin_headers: dict[str, str]) -> None:
    assert client.delete("/api/v1/tags/general/nothing", headers=admin_headers).status_code == 404
    assert client.patch("/api/v1/tags/nowhere/x", json={"new_tag": "y"}, headers=admin_headers).status_code == 404


def test_users_cannot_rename_or_delete_tags(client: TestClient, user_headers: dict[str, str]) -> None:
    assert client.delete("/api/v1/tags/general/summer", headers=user_headers).status_code == 403
    assert client.patch("/api/v1/tags/general/summer", json={"new_tag": "y"}, headers=user_headers).status_code == 403
