# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import hashlib
import io
import json
import os

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pictorio_db.api.v1 import _upload_receiver
from pictorio_db.config import Config
from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    client.app.state.auth.create_user("kid", PASSWORD, Role.USER)
    login = {"username": "kid", "password": PASSWORD, "device_name": "t"}
    response = client.post("/api/v1/auth/tokens", json=login)
    return {"Authorization": f"Bearer {response.json()['token']}"}


def jpeg_bytes(size: tuple[int, int] = (40, 30), colour: str = "teal") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG")
    return buffer.getvalue()


def noise_jpeg_bytes(size: tuple[int, int]) -> bytes:
    """Random pixels compress badly, so the file is large for its size in pixels."""
    buffer = io.BytesIO()
    Image.effect_noise(size, 100).convert("RGB").save(buffer, format="JPEG")
    return buffer.getvalue()


def upload(
    client: TestClient,
    headers: dict[str, str],
    content: bytes,
    metadata: dict[str, object] | str | None = None,
):  # -> httpx Response
    default_metadata = {"original_filename": "beach.jpg"}
    metadata_text = metadata if isinstance(metadata, str) else json.dumps(metadata or default_metadata)
    return client.post(
        "/api/v1/images",
        headers=headers,
        files={"file": ("beach.jpg", content, "image/jpeg")},
        data={"metadata": metadata_text},
    )


def incoming_files(config: Config) -> list[str]:
    incoming_dir = config.library_dir / ".incoming"
    return os.listdir(incoming_dir) if incoming_dir.exists() else []


@pytest.fixture
def uploaded(client: TestClient, headers: dict[str, str]) -> dict:
    content = jpeg_bytes()
    metadata = {"original_filename": "beach.jpg", "tags": ["category:photo", "summer"]}
    response = upload(client, headers, content, metadata)
    assert response.status_code == 201
    return response.json() | {"content": content}


# --- Upload

def test_upload_returns_the_image_object(client: TestClient, headers: dict[str, str]) -> None:
    content = jpeg_bytes()
    metadata = {
        "original_filename": "beach.jpg",
        "file_mtime": "2018-07-14T16:02:11",
        "client_sha256": hashlib.sha256(content).hexdigest(),
        "tags": ["category:photo", "summer"],
    }

    response = upload(client, headers, content, metadata)

    assert response.status_code == 201
    image = response.json()
    assert response.headers["location"] == f"/api/v1/images/{image['id']}"
    assert image["sha256"] == hashlib.sha256(content).hexdigest()
    assert (image["mime_type"], image["width"], image["height"]) == ("image/jpeg", 40, 30)
    assert (image["taken_at"], image["taken_at_source"]) == ("2018-07-14T16:02:11", "file_mtime")
    assert image["tags"] == ["category:photo", "general:summer"]
    assert image["imported_at"].endswith("Z")
    assert image["links"] == {
        "self": f"/api/v1/images/{image['id']}",
        "file": f"/api/v1/images/{image['id']}/file",
        "thumbnail": f"/api/v1/images/{image['id']}/thumbnail",
    }


def test_upload_needs_a_login(client: TestClient) -> None:
    assert upload(client, {}, jpeg_bytes()).status_code == 401


def test_duplicate_upload_names_the_existing_image(
    client: TestClient, headers: dict[str, str], uploaded: dict
) -> None:
    response = upload(client, headers, uploaded["content"])

    assert response.status_code == 409
    assert response.json()["existing_image_id"] == uploaded["id"]


@pytest.mark.parametrize(
    ("content", "metadata", "status", "code"),
    [
        (b"not an image", {"original_filename": "a.jpg"}, 415, "unsupported_media_type"),
        (None, {"original_filename": "a.jpg", "client_sha256": "0" * 64}, 422, "checksum_mismatch"),
        (None, {"original_filename": "a.jpg", "tags": ["a|b"]}, 422, "invalid_tag"),
    ],
)
def test_refused_uploads_leave_nothing_behind(
    client: TestClient,
    headers: dict[str, str],
    config: Config,
    content: bytes | None,
    metadata: dict,
    status: int,
    code: str,
) -> None:
    response = upload(client, headers, content or jpeg_bytes(), metadata)

    assert (response.status_code, response.json()["code"]) == (status, code)
    assert incoming_files(config) == []


@pytest.mark.parametrize(
    ("metadata", "field"),
    [
        ("{not json", "metadata"),
        ({"tags": ["summer"]}, "metadata.original_filename"),
        ({"original_filename": "a.jpg", "client_sha256": "short"}, "metadata.client_sha256"),
    ],
)
def test_invalid_metadata_names_the_field(
    client: TestClient, headers: dict[str, str], config: Config, metadata: dict | str, field: str
) -> None:
    response = upload(client, headers, jpeg_bytes(), metadata)

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"].startswith(field)
    assert incoming_files(config) == []


def test_missing_part_is_named(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/images",
        headers=headers,
        data={"metadata": '{"original_filename": "a.jpg"}'},
        files={"other": ("x", b"x")},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0] == {"field": "file", "message": "This part is missing."}


def test_body_must_be_multipart(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/api/v1/images", headers=headers, json={"original_filename": "a.jpg"})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "body"


@pytest.mark.parametrize(
    ("image_size", "parsing_started"),
    [((300, 200), True), ((1000, 800), False)],
    ids=["found while receiving", "refused by its announced size"],
)
def test_too_large_upload_is_refused(
    client: TestClient,
    headers: dict[str, str],
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    image_size: tuple[int, int],
    parsing_started: bool,
) -> None:
    client.app.state.settings.set("max_upload_bytes", 1000)
    content = noise_jpeg_bytes(image_size)
    parsers_created = []
    real_parser = _upload_receiver.MultipartParser
    monkeypatch.setattr(
        _upload_receiver, "MultipartParser", lambda *arguments: parsers_created.append(1) or real_parser(*arguments)
    )

    response = upload(client, headers, content)

    assert response.status_code == 413
    assert (response.json()["code"], response.json()["limit_bytes"]) == ("file_too_large", 1000)
    assert bool(parsers_created) is parsing_started
    assert incoming_files(config) == []


# --- Reading images back

def test_get_image_returns_the_same_object(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    response = client.get(f"/api/v1/images/{uploaded['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json() == {key: value for key, value in uploaded.items() if key != "content"}


def test_unknown_image_is_not_found(client: TestClient, headers: dict[str, str]) -> None:
    for path in ("/api/v1/images/999", "/api/v1/images/999/file", "/api/v1/images/999/thumbnail"):
        assert client.get(path, headers=headers).status_code == 404


def test_file_is_the_original(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    response = client.get(f"/api/v1/images/{uploaded['id']}/file", headers=headers)

    assert response.status_code == 200
    assert response.content == uploaded["content"]
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["etag"] == f'"{uploaded["sha256"]}"'
    assert response.headers["content-disposition"] == 'inline; filename="beach.jpg"'


def test_file_unchanged_since_last_time_is_304(
    client: TestClient, headers: dict[str, str], uploaded: dict
) -> None:
    response = client.get(
        f"/api/v1/images/{uploaded['id']}/file", headers=headers | {"If-None-Match": f'"{uploaded["sha256"]}"'}
    )

    assert response.status_code == 304
    assert response.content == b""


def test_file_supports_ranges(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    response = client.get(f"/api/v1/images/{uploaded['id']}/file", headers=headers | {"Range": "bytes=0-9"})

    assert response.status_code == 206
    assert response.content == uploaded["content"][:10]


@pytest.mark.parametrize("size", [256, 1024])
def test_thumbnail_is_cacheable_webp(client: TestClient, headers: dict[str, str], uploaded: dict, size: int) -> None:
    response = client.get(f"/api/v1/images/{uploaded['id']}/thumbnail", params={"size": size}, headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert response.headers["etag"] == f'"{uploaded["sha256"]}-{size}"'
    assert Image.open(io.BytesIO(response.content)).format == "WEBP"


def test_thumbnail_size_must_be_256_or_1024(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    response = client.get(f"/api/v1/images/{uploaded['id']}/thumbnail", params={"size": 512}, headers=headers)

    assert response.status_code == 422


def test_thumbnail_unchanged_since_last_time_is_304(
    client: TestClient, headers: dict[str, str], uploaded: dict
) -> None:
    etag = f'"{uploaded["sha256"]}-256"'

    response = client.get(f"/api/v1/images/{uploaded['id']}/thumbnail", headers=headers | {"If-None-Match": etag})

    assert response.status_code == 304


def test_missing_thumbnail_is_made_again(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    client.app.state.thumbnails.delete_thumbnails(uploaded["sha256"])

    response = client.get(f"/api/v1/images/{uploaded['id']}/thumbnail", headers=headers)

    assert response.status_code == 200
    assert client.app.state.thumbnails.thumbnail_path(uploaded["sha256"], 256).exists()


# --- Searching

def test_search_needs_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/images").status_code == 401


def test_search_returns_image_objects(client: TestClient, headers: dict[str, str], uploaded: dict) -> None:
    response = client.get("/api/v1/images", params={"q": "category:photo summer"}, headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [uploaded["id"]]
    assert body["items"][0]["tags"] == ["category:photo", "general:summer"]
    assert body["next_cursor"] is None
    assert body["effective_query"] == "category:photo summer"


def test_search_pages_with_the_cursor(client: TestClient, headers: dict[str, str]) -> None:
    for colour in ("red", "green", "blue"):
        upload(client, headers, jpeg_bytes(colour=colour))

    first = client.get("/api/v1/images", params={"limit": 2}, headers=headers).json()
    second = client.get("/api/v1/images", params={"limit": 2, "cursor": first["next_cursor"]}, headers=headers).json()

    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert second["next_cursor"] is None


def test_invalid_query_says_where(client: TestClient, headers: dict[str, str]) -> None:
    response = client.get("/api/v1/images", params={"q": "summer beach,,sand"}, headers=headers)

    assert response.status_code == 400
    assert (response.json()["code"], response.json()["position"]) == ("invalid_query", 13)


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"sort": "size"}, {"sort": "random"}])
def test_invalid_search_parameters(client: TestClient, headers: dict[str, str], params: dict) -> None:
    assert client.get("/api/v1/images", params=params, headers=headers).status_code == 422
