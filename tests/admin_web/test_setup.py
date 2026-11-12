# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest
from fastapi.testclient import TestClient

from pictorio_db.services.auth import AuthService, Role

PASSWORD = "correct horse battery"


@pytest.fixture
def auth(client: TestClient) -> AuthService:
    return client.app.state.auth


def setup_form(setup_code: str, username: str = "apo", password: str = PASSWORD,
               password_repeated: str = PASSWORD) -> dict[str, str]:
    return {
        "setup_code": setup_code,
        "username": username,
        "password": password,
        "password_repeated": password_repeated,
    }


def current_setup_code(auth: AuthService) -> str:
    setup_code = auth.setup_code()
    assert setup_code is not None
    return setup_code


def test_shows_the_form_while_no_admin_exists(client: TestClient) -> None:
    response = client.get("/admin/setup")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'name="setup_code"' in response.text


def test_creates_the_first_admin(client: TestClient, auth: AuthService) -> None:
    response = client.post("/admin/setup", data=setup_form(current_setup_code(auth), username="Apo"))

    assert response.status_code == 200
    assert "<strong>apo</strong> has been created" in response.text
    assert client.get("/api/v1/server/info").json()["setup_required"] is False
    login = {"username": "apo", "password": PASSWORD, "device_name": "laptop"}
    assert client.post("/api/v1/auth/tokens", json=login).status_code == 201


def test_wrong_code_shows_the_form_again(client: TestClient, auth: AuthService) -> None:
    response = client.post("/admin/setup", data=setup_form("AAAA-BBBB-CCCC", username="apo"))

    assert response.status_code == 403
    assert "Wrong setup code" in response.text
    assert 'value="apo"' in response.text  # the username is kept, the password and code are not
    assert auth.is_setup_required()


def test_different_passwords_show_the_form_again(client: TestClient, auth: AuthService) -> None:
    form = setup_form(current_setup_code(auth), password_repeated="another password")

    response = client.post("/admin/setup", data=form)

    assert response.status_code == 422
    assert "The two passwords differ." in response.text
    assert auth.is_setup_required()


def test_invalid_username_says_what_is_allowed(client: TestClient, auth: AuthService) -> None:
    response = client.post("/admin/setup", data=setup_form(current_setup_code(auth), username="with space"))

    assert response.status_code == 422
    assert "Username: 1 to 32 characters" in response.text


def test_user_input_is_escaped(client: TestClient) -> None:
    response = client.post("/admin/setup", data=setup_form("wrong", username="<script>x</script>"))

    assert "<script>x</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_says_setup_is_done_once_an_admin_exists(client: TestClient, auth: AuthService) -> None:
    auth.create_user("apo", PASSWORD, Role.ADMIN)

    response = client.get("/admin/setup")

    assert response.status_code == 200
    assert "An admin account exists already." in response.text
    assert 'name="setup_code"' not in response.text


def test_second_setup_is_refused(client: TestClient, auth: AuthService) -> None:
    setup_code = current_setup_code(auth)
    client.post("/admin/setup", data=setup_form(setup_code))

    response = client.post("/admin/setup", data=setup_form(setup_code, username="intruder"))

    assert response.status_code == 409
    assert "An admin account exists already." in response.text
