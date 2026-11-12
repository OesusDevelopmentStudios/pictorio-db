# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest
from fastapi.testclient import TestClient

from pictorio_db.services.auth import AuthService, Role

PASSWORD = "correct horse battery"


@pytest.fixture
def auth(client: TestClient) -> AuthService:
    return client.app.state.auth


def log_in(client: TestClient, username: str, device_name: str = "laptop") -> str:
    response = client.post(
        "/api/v1/auth/tokens", json={"username": username, "password": PASSWORD, "device_name": device_name}
    )
    assert response.status_code == 201
    return response.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_token_and_user(client: TestClient, auth: AuthService) -> None:
    user = auth.create_user("kid", PASSWORD, Role.USER)

    response = client.post(
        "/api/v1/auth/tokens", json={"username": "kid", "password": PASSWORD, "device_name": "laptop"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("pk_")
    assert body["user"] == {"id": user.id, "username": "kid", "role": "user"}


def test_wrong_password_is_not_authenticated(client: TestClient, auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)

    response = client.post(
        "/api/v1/auth/tokens", json={"username": "kid", "password": "wrong password", "device_name": "laptop"}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


def test_login_without_device_name_is_invalid(client: TestClient) -> None:
    response = client.post("/api/v1/auth/tokens", json={"username": "kid", "password": PASSWORD})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body.device_name"


def test_too_many_failed_logins_are_refused_for_a_while(client: TestClient, auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    wrong_login = {"username": "kid", "password": "wrong password", "device_name": "laptop"}
    for _ in range(10):
        client.post("/api/v1/auth/tokens", json=wrong_login)

    response = client.post("/api/v1/auth/tokens", json=wrong_login)

    assert response.status_code == 429
    assert response.json()["code"] == "too_many_attempts"
    assert int(response.headers["retry-after"]) > 0


def test_me_returns_the_logged_in_user(client: TestClient, auth: AuthService) -> None:
    user = auth.create_user("kid", PASSWORD, Role.USER)
    token = log_in(client, "kid")

    response = client.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {"id": user.id, "username": "kid", "role": "user", "restricted_tags": []}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer pk_unknown"}, {"Authorization": "Basic a2lkOnBhc3N3b3Jk"}],
    ids=["no token", "unknown token", "not a bearer token"],
)
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/api/v1/auth/me"), ("GET", "/api/v1/auth/tokens"), ("DELETE", "/api/v1/auth/tokens/1")],
)
def test_protected_endpoints_need_a_valid_token(
    client: TestClient, method: str, path: str, headers: dict[str, str]
) -> None:
    response = client.request(method, path, headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "not_authenticated"


def test_lists_own_devices_and_marks_the_current_one(client: TestClient, auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    laptop_token = log_in(client, "kid", "laptop")
    log_in(client, "kid", "phone")

    response = client.get("/api/v1/auth/tokens", headers=bearer(laptop_token))

    assert response.status_code == 200
    devices = response.json()
    assert [(device["device_name"], device["is_current"]) for device in devices] == [
        ("laptop", True),
        ("phone", False),
    ]
    assert devices[0]["created_at"].endswith("Z")  # UTC, as the API promises


def test_revoking_the_current_token_logs_out(client: TestClient, auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    token = log_in(client, "kid")
    token_id = client.get("/api/v1/auth/tokens", headers=bearer(token)).json()[0]["token_id"]

    response = client.delete(f"/api/v1/auth/tokens/{token_id}", headers=bearer(token))

    assert response.status_code == 204
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_cannot_revoke_another_users_token(client: TestClient, auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    auth.create_user("apo", PASSWORD, Role.ADMIN)
    kids_token = log_in(client, "kid")
    kids_token_id = client.get("/api/v1/auth/tokens", headers=bearer(kids_token)).json()[0]["token_id"]
    admin_token = log_in(client, "apo")

    response = client.delete(f"/api/v1/auth/tokens/{kids_token_id}", headers=bearer(admin_token))

    assert response.status_code == 404
    assert client.get("/api/v1/auth/me", headers=bearer(kids_token)).status_code == 200
