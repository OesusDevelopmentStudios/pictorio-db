# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What a user with restricted tags can see and do. An admin uploads a safe and an nsfw image; the user
"kid" is restricted from rating:nsfw."""

import io
import json
import os
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pictorio_db.config import Config
from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


@dataclass
class Setup:
    admin: dict[str, str]  # request headers
    kid: dict[str, str]
    kid_id: int
    safe_id: int
    nsfw_id: int
    nsfw_bytes: bytes


def jpeg(colour: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="JPEG")
    return buffer.getvalue()


def upload(client: TestClient, headers: dict[str, str], content: bytes, tags: list[str]):  # -> httpx Response
    metadata = json.dumps({"original_filename": "a.jpg", "tags": tags})
    files = {"file": ("a.jpg", content)}
    return client.post("/api/v1/images", headers=headers, files=files, data={"metadata": metadata})


def log_in(client: TestClient, username: str, role: Role) -> tuple[dict[str, str], int]:
    user = client.app.state.auth.create_user(username, PASSWORD, role)
    login = {"username": username, "password": PASSWORD, "device_name": "t"}
    token = client.post("/api/v1/auth/tokens", json=login).json()["token"]
    return {"Authorization": f"Bearer {token}"}, user.id


@pytest.fixture
def setup(client: TestClient) -> Setup:
    admin, _admin_id = log_in(client, "apo", Role.ADMIN)
    kid, kid_id = log_in(client, "kid", Role.USER)
    client.app.state.access.set_restricted_terms(kid_id, ["rating:nsfw"])
    nsfw_bytes = jpeg("red")
    safe_id = upload(client, admin, jpeg("green"), ["rating:sfw", "summer"]).json()["id"]
    nsfw_id = upload(client, admin, nsfw_bytes, ["rating:nsfw", "summer"]).json()["id"]
    return Setup(admin, kid, kid_id, safe_id, nsfw_id, nsfw_bytes)


def found(client: TestClient, headers: dict[str, str], params: dict[str, object]) -> tuple[set[int], str]:
    body = client.get("/api/v1/images", params=params, headers=headers).json()
    return {item["id"] for item in body["items"]}, body["effective_query"]


def tags_of(client: TestClient, setup: Setup, image_id: int) -> list[str]:
    return client.get(f"/api/v1/images/{image_id}", headers=setup.admin).json()["tags"]


# --- Seeing and finding

@pytest.mark.parametrize(
    "params",
    [{}, {"q": "rating:nsfw"}, {"q": "summer", "apply_hidden_filters": False}],
    ids=["everything", "searching for the restricted tag", "without hidden filters"],
)
def test_search_never_shows_restricted_images(client: TestClient, setup: Setup, params: dict[str, object]) -> None:
    images, effective_query = found(client, setup.kid, params)

    assert setup.nsfw_id not in images
    assert effective_query == params.get("q", "")  # kid has no hidden filters; restrictions are never shown


def test_admin_sees_everything(client: TestClient, setup: Setup) -> None:
    assert found(client, setup.admin, {})[0] == {setup.safe_id, setup.nsfw_id}


@pytest.mark.parametrize("suffix", ["", "/file", "/thumbnail"])
def test_restricted_image_does_not_exist_for_the_user(client: TestClient, setup: Setup, suffix: str) -> None:
    assert client.get(f"/api/v1/images/{setup.nsfw_id}{suffix}", headers=setup.kid).status_code == 404
    assert client.get(f"/api/v1/images/{setup.nsfw_id}{suffix}", headers=setup.admin).status_code == 200
    assert client.get(f"/api/v1/images/{setup.safe_id}{suffix}", headers=setup.kid).status_code == 200


def test_restricted_tags_are_never_suggested(client: TestClient, setup: Setup) -> None:
    def suggestions(headers: dict[str, str]) -> list[str]:
        response = client.get("/api/v1/tags", params={"prefix": "rating:"}, headers=headers)
        return [item["tag"] for item in response.json()["items"]]

    assert suggestions(setup.kid) == ["rating:sfw"]
    assert set(suggestions(setup.admin)) == {"rating:nsfw", "rating:sfw"}


def test_lifting_a_restriction_applies_at_once(client: TestClient, setup: Setup) -> None:
    client.patch(f"/api/v1/admin/users/{setup.kid_id}", json={"restricted_tags": []}, headers=setup.admin)

    assert setup.nsfw_id in found(client, setup.kid, {"apply_hidden_filters": False})[0]


# --- Uploading and tagging

def test_upload_with_a_restricted_tag_is_refused(client: TestClient, setup: Setup, config: Config) -> None:
    response = upload(client, setup.kid, jpeg("blue"), ["rating:nsfw"])

    assert response.status_code == 403
    assert (response.json()["code"], response.json()["tags"]) == ("tag_restricted", ["rating:nsfw"])
    assert os.listdir(config.library_dir / ".incoming") == []
    assert len(found(client, setup.admin, {})[0]) == 2  # nothing was stored


def test_duplicate_of_a_restricted_image_does_not_say_which(client: TestClient, setup: Setup) -> None:
    response = upload(client, setup.kid, setup.nsfw_bytes, ["summer"])

    assert response.status_code == 409
    assert "existing_image_id" not in response.json()
    assert "sha256" in response.json()


def test_adding_a_restricted_tag_is_refused(client: TestClient, setup: Setup) -> None:
    response = client.patch(f"/api/v1/images/{setup.safe_id}", json={"add_tags": ["rating:nsfw"]}, headers=setup.kid)

    assert (response.status_code, response.json()["code"]) == (403, "tag_restricted")
    assert "rating:sfw" in tags_of(client, setup, setup.safe_id)


def test_restricted_image_cannot_be_tagged(client: TestClient, setup: Setup) -> None:
    response = client.patch(f"/api/v1/images/{setup.nsfw_id}", json={"add_tags": ["beach"]}, headers=setup.kid)

    assert response.status_code == 404
    assert "general:beach" not in tags_of(client, setup, setup.nsfw_id)


def test_bulk_change_with_a_restricted_image_changes_nothing(client: TestClient, setup: Setup) -> None:
    body = {"image_ids": [setup.safe_id, setup.nsfw_id], "add_tags": ["album:trip"]}

    response = client.post("/api/v1/images/bulk-tags", json=body, headers=setup.kid)

    assert response.status_code == 404
    assert "album:trip" not in tags_of(client, setup, setup.safe_id)


# --- Every image endpoint, as a restricted user against a restricted image

def expect_not_found(method: str, path: str) -> Callable[[TestClient, Setup], None]:
    def check(client: TestClient, setup: Setup) -> None:
        body = {"add_tags": ["beach"]} if method == "PATCH" else None
        response = client.request(method, path.format(image_id=setup.nsfw_id), json=body, headers=setup.kid)
        assert response.status_code == 404

    return check


def check_search_excludes(client: TestClient, setup: Setup) -> None:
    assert setup.nsfw_id not in found(client, setup.kid, {"q": "summer", "apply_hidden_filters": False})[0]


def check_upload_refuses(client: TestClient, setup: Setup) -> None:
    assert upload(client, setup.kid, jpeg("blue"), ["rating:nsfw"]).status_code == 403
    duplicate = upload(client, setup.kid, setup.nsfw_bytes, [])
    assert duplicate.status_code == 409 and "existing_image_id" not in duplicate.json()


def check_bulk_refuses(client: TestClient, setup: Setup) -> None:
    body = {"image_ids": [setup.nsfw_id], "add_tags": ["beach"]}
    assert client.post("/api/v1/images/bulk-tags", json=body, headers=setup.kid).status_code == 404


def check_autocomplete_hides(client: TestClient, setup: Setup) -> None:
    response = client.get("/api/v1/tags", params={"prefix": "rating:"}, headers=setup.kid)
    assert "rating:nsfw" not in [item["tag"] for item in response.json()["items"]]


# Every route that reads or changes images, and how it must treat a restricted image. A new image route
# must be added here; test_every_image_route_is_checked fails until it is.
ACCESS_RULES = {
    ("GET", "/api/v1/images"): check_search_excludes,
    ("POST", "/api/v1/images"): check_upload_refuses,
    ("POST", "/api/v1/images/bulk-tags"): check_bulk_refuses,
    ("GET", "/api/v1/images/{image_id}"): expect_not_found("GET", "/api/v1/images/{image_id}"),
    ("PATCH", "/api/v1/images/{image_id}"): expect_not_found("PATCH", "/api/v1/images/{image_id}"),
    ("GET", "/api/v1/images/{image_id}/file"): expect_not_found("GET", "/api/v1/images/{image_id}/file"),
    ("GET", "/api/v1/images/{image_id}/thumbnail"): expect_not_found("GET", "/api/v1/images/{image_id}/thumbnail"),
    ("GET", "/api/v1/tags"): check_autocomplete_hides,
}


@pytest.mark.parametrize("route", list(ACCESS_RULES), ids=[f"{method} {path}" for method, path in ACCESS_RULES])
def test_restricted_image_stays_hidden_on_every_route(
    client: TestClient, setup: Setup, route: tuple[str, str]
) -> None:
    ACCESS_RULES[route](client, setup)


def test_every_image_route_is_checked(client: TestClient) -> None:
    """Reads the routes from the API schema, which lists every REST route the app serves."""
    image_routes = {
        (method.upper(), path)
        for path, operations in client.app.openapi()["paths"].items()
        if path.startswith(("/api/v1/images", "/api/v1/tags"))
        for method in operations
    }

    assert image_routes == set(ACCESS_RULES), "Add the new image route to ACCESS_RULES with its expected behaviour."
