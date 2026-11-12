# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest
from fastapi.testclient import TestClient

from pictorio_db.services.auth import AuthService, Role

PASSWORD = "correct horse battery"


def headers_for(client: TestClient, username: str, role: Role) -> dict[str, str]:
    auth: AuthService = client.app.state.auth
    auth.create_user(username, PASSWORD, role)
    response = client.post(
        "/api/v1/auth/tokens", json={"username": username, "password": PASSWORD, "device_name": "test"}
    )
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return headers_for(client, "apo", Role.ADMIN)


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    return headers_for(client, "kid", Role.USER)


def test_listing_needs_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/namespaces").status_code == 401


def test_every_user_can_list_namespaces(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/namespaces", headers=user_headers)

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "name": "category",
        "single_value": True,
        "is_builtin": True,
        "in_path_template": True,
    }


def test_only_admins_create_namespaces(client: TestClient, user_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/namespaces", json={"name": "weather"}, headers=user_headers)

    assert response.status_code == 403


def test_admin_creates_a_namespace(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post("/api/v1/namespaces", json={"name": "Weather"}, headers=admin_headers)

    assert response.status_code == 201
    assert response.json() == {
        "name": "weather",
        "single_value": False,
        "is_builtin": False,
        "in_path_template": False,
    }


@pytest.mark.parametrize(
    ("name", "status", "code"), [("album", 409, "already_exists"), ("date", 422, "validation_error")]
)
def test_refuses_existing_and_invalid_names(
    client: TestClient, admin_headers: dict[str, str], name: str, status: int, code: str
) -> None:
    response = client.post("/api/v1/namespaces", json={"name": name}, headers=admin_headers)

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_admin_deletes_an_unused_namespace(client: TestClient, admin_headers: dict[str, str]) -> None:
    client.post("/api/v1/namespaces", json={"name": "weather"}, headers=admin_headers)

    response = client.delete("/api/v1/namespaces/weather", headers=admin_headers)

    assert response.status_code == 204
    names = [item["name"] for item in client.get("/api/v1/namespaces", headers=admin_headers).json()["items"]]
    assert "weather" not in names


def test_builtin_namespace_is_in_use(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.delete("/api/v1/namespaces/album", headers=admin_headers)

    assert (response.status_code, response.json()["code"]) == (409, "namespace_in_use")


def test_in_path_template_follows_the_stored_template(client: TestClient, admin_headers: dict[str, str]) -> None:
    client.post("/api/v1/namespaces", json={"name": "weather"}, headers=admin_headers)
    client.app.state.storage.set_path_template("{weather}/{year}")

    items = client.get("/api/v1/namespaces", headers=admin_headers).json()["items"]
    deletion = client.delete("/api/v1/namespaces/weather", headers=admin_headers)

    assert {item["name"] for item in items if item["in_path_template"]} == {"weather"}
    assert deletion.status_code == 409
    assert deletion.json()["detail"] == "The library's path template uses this namespace."
