# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pictorio_db.utils.problems import PROBLEM_MEDIA_TYPE, Problem, install_problem_handlers


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install_problem_handlers(app)

    @app.get("/duplicate")
    def duplicate() -> None:
        raise Problem(409, "duplicate_image", "Image already exists", "Same SHA-256.", existing_image_id=1234)

    @app.get("/rate-limited")
    def rate_limited() -> None:
        raise Problem(429, "too_many_attempts", "Too many attempts", headers={"Retry-After": "900"})

    @app.get("/count")
    def count(limit: int) -> int:
        return limit

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("bug")

    return TestClient(app, raise_server_exceptions=False)


def test_problem_has_rfc9457_fields_and_extras(client: TestClient) -> None:
    response = client.get("/duplicate")

    assert response.status_code == 409
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json() == {
        "type": "https://pictorio.invalid/problems/duplicate-image",
        "title": "Image already exists",
        "status": 409,
        "code": "duplicate_image",
        "detail": "Same SHA-256.",
        "existing_image_id": 1234,
    }


def test_problem_can_set_headers(client: TestClient) -> None:
    response = client.get("/rate-limited")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "900"
    assert "detail" not in response.json()


def test_unknown_path_is_not_found_problem(client: TestClient) -> None:
    response = client.get("/no-such-path")

    assert response.status_code == 404
    assert response.headers["content-type"] == PROBLEM_MEDIA_TYPE
    assert response.json()["code"] == "not_found"


def test_invalid_parameter_is_validation_problem(client: TestClient) -> None:
    response = client.get("/count", params={"limit": "many"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["errors"][0]["field"] == "query.limit"


def test_unexpected_error_returns_trace_id_that_is_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = client.get("/crash")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["trace_id"] in caplog.text
    assert "bug" not in response.text  # no internals leak to the client
