# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""A browser logged in to the admin pages: the test client keeps the session cookie like a browser."""

import re

import pytest
from fastapi.testclient import TestClient

from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


def csrf_token_in(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', html)
    assert match is not None, "the page has no form with a CSRF token"
    return match.group(1)


@pytest.fixture
def admin_browser(client: TestClient) -> TestClient:
    client.app.state.auth.create_user("apo", PASSWORD, Role.ADMIN)
    response = client.post("/admin/login", data={"username": "apo", "password": PASSWORD})
    assert response.status_code == 200  # followed the redirect to the overview
    return client
