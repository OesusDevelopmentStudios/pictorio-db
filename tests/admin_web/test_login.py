# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from pictorio_db.db.models import ApiToken
from pictorio_db.services.auth import Role
from pictorio_db.utils.time import utc_now

from .conftest import PASSWORD, csrf_token_in


def log_in(client: TestClient, username: str, password: str = PASSWORD, next: str | None = None):  # -> Response
    form = {"username": username, "password": password} | ({} if next is None else {"next": next})
    return client.post("/admin/login", data=form, follow_redirects=False)


@pytest.fixture
def admin(client: TestClient) -> None:
    client.app.state.auth.create_user("apo", PASSWORD, Role.ADMIN)


# --- Logging in

def test_admin_pages_send_you_to_the_login(client: TestClient) -> None:
    response = client.get("/admin", follow_redirects=False)

    assert (response.status_code, response.headers["location"]) == (303, "/admin/login?next=/admin")


def test_login_sets_a_session_cookie_and_returns_to_the_page(client: TestClient, admin: None) -> None:
    response = log_in(client, "apo", next="/admin")

    assert (response.status_code, response.headers["location"]) == (303, "/admin")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("pictorio_admin=")
    for attribute in ("HttpOnly", "Path=/admin", "SameSite=strict"):
        assert attribute in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()  # forgotten when the browser closes
    assert "apo" in client.get("/admin").text


@pytest.mark.parametrize(
    "username, password, role, message",
    [
        ("apo", "wrong password", Role.ADMIN, "Wrong username or password."),
        ("nobody", PASSWORD, Role.ADMIN, "Wrong username or password."),
        ("kid", PASSWORD, Role.USER, "Only admins can use these pages."),
    ],
    ids=["wrong password", "unknown user", "not an admin"],
)
def test_failed_login_says_why(client: TestClient, username: str, password: str, role: Role, message: str) -> None:
    client.app.state.auth.create_user("kid" if role == Role.USER else "apo", PASSWORD, role)

    response = log_in(client, username, password)

    assert response.status_code in (401, 403)
    assert message in response.text
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("next", ["https://example.org/", "//example.org/admin", "/api/v1/images"])
def test_login_never_returns_to_another_site(client: TestClient, admin: None, next: str) -> None:
    assert log_in(client, "apo", next=next).headers["location"] == "/admin"


def test_login_page_points_to_the_setup_until_an_admin_exists(client: TestClient) -> None:
    assert 'href="/admin/setup"' in client.get("/admin/login").text


# --- The session

def test_session_ends_after_twelve_hours(admin_browser: TestClient) -> None:
    with admin_browser.app.state.database.session() as session:  # as if the login were 12 hours old
        session.execute(update(ApiToken).values(expires_at=utc_now() - timedelta(seconds=1)))
        session.commit()

    assert admin_browser.get("/admin", follow_redirects=False).status_code == 303


def test_admin_who_became_a_user_is_logged_out(admin_browser: TestClient) -> None:
    auth = admin_browser.app.state.auth
    auth.create_user("other_admin", PASSWORD, Role.ADMIN)
    apo = next(user for user in auth.list_users() if user.username == "apo")
    auth.update_user(apo.id, role=Role.USER)

    assert admin_browser.get("/admin", follow_redirects=False).status_code == 303


def test_session_is_listed_with_the_devices(admin_browser: TestClient) -> None:
    apo = admin_browser.app.state.auth.list_users()[0]

    [token] = admin_browser.app.state.auth.list_tokens(apo.id)

    assert token.device_name == "Web admin"
    assert token.expires_at is not None


# --- Logging out

def test_logout_ends_the_session(admin_browser: TestClient) -> None:
    csrf_token = csrf_token_in(admin_browser.get("/admin").text)

    response = admin_browser.post("/admin/logout", data={"csrf_token": csrf_token}, follow_redirects=False)

    assert (response.status_code, response.headers["location"]) == (303, "/admin/login")
    assert admin_browser.app.state.auth.list_tokens(admin_browser.app.state.auth.list_users()[0].id) == []
    assert admin_browser.get("/admin", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("csrf_token", [None, "0" * 64], ids=["missing", "wrong"])
def test_form_without_the_right_csrf_token_is_refused(admin_browser: TestClient, csrf_token: str | None) -> None:
    data = {} if csrf_token is None else {"csrf_token": csrf_token}

    response = admin_browser.post("/admin/logout", data=data)

    assert response.status_code == 403
    assert "This form has expired" in response.text
    assert admin_browser.get("/admin", follow_redirects=False).status_code == 200  # still logged in
