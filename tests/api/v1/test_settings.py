# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin/settings, and what the settings change elsewhere."""

import io
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pictorio_db.config import Config
from pictorio_db.services.auth import Role

PASSWORD = "correct horse battery"


def log_in(client: TestClient, username: str, role: Role) -> dict[str, str]:
    client.app.state.auth.create_user(username, PASSWORD, role)
    login = {"username": username, "password": PASSWORD, "device_name": "t"}
    return {"Authorization": f"Bearer {client.post('/api/v1/auth/tokens', json=login).json()['token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return log_in(client, "apo", Role.ADMIN)


def upload(client: TestClient, headers: dict[str, str], tags: list[str], colour: str = "teal"):  # -> httpx Response
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), colour).save(buffer, format="JPEG")
    metadata = json.dumps({"original_filename": "beach.jpg", "tags": tags})
    files = {"file": ("beach.jpg", buffer.getvalue())}
    return client.post("/api/v1/images", headers=headers, files=files, data={"metadata": metadata})


def wait_for_job(client: TestClient, headers: dict[str, str], job_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("done", "failed"):
            return job

        time.sleep(0.01)

    raise AssertionError(f"Job {job_id} did not finish in time")


def test_admin_sees_the_settings(client: TestClient, admin: dict[str, str], config: Config) -> None:
    response = client.get("/api/v1/admin/settings", headers=admin)

    assert response.json() == {
        "path_template": "{category}/{author}/{year}",
        "max_upload_bytes": 200 * 1024 * 1024,
        "rating_values": ["sfw", "nsfw"],
        "library_dir": str(config.library_dir),
        "import_dir": None,
    }


def test_only_admins_see_and_change_settings(client: TestClient) -> None:
    kid = log_in(client, "kid", Role.USER)

    assert client.get("/api/v1/admin/settings", headers=kid).status_code == 403
    assert client.patch("/api/v1/admin/settings", json={"max_upload_bytes": 1048576}, headers=kid).status_code == 403


def test_new_path_template_moves_the_files(client: TestClient, admin: dict[str, str]) -> None:
    image_id = upload(client, admin, ["category:photo"]).json()["id"]

    response = client.patch("/api/v1/admin/settings", json={"path_template": "{category}"}, headers=admin)

    assert (response.status_code, response.json()["path_template"]) == (200, "{category}")
    job = wait_for_job(client, admin, response.json()["job_id"])
    assert (job["kind"], job["result"]["moved"]) == ("relayout", 1)
    storage_path = client.get(f"/api/v1/images/{image_id}", headers=admin).json()["storage_path"]
    assert storage_path.startswith("photo/") and storage_path.count("/") == 1


def test_other_changes_start_no_job(client: TestClient, admin: dict[str, str]) -> None:
    response = client.patch("/api/v1/admin/settings", json={"max_upload_bytes": 1048576}, headers=admin)

    assert (response.json()["max_upload_bytes"], response.json()["job_id"]) == (1048576, None)
    assert client.get("/api/v1/jobs", headers=admin).json() == []


@pytest.mark.parametrize(
    "changes",
    [{"path_template": "{nonsense}"}, {"max_upload_bytes": 1000}, {"rating_values": []}],
    ids=["unknown placeholder", "upload limit too small", "no ratings"],
)
def test_invalid_setting_is_refused(client: TestClient, admin: dict[str, str], changes: dict[str, Any]) -> None:
    before = client.get("/api/v1/admin/settings", headers=admin).json()

    response = client.patch("/api/v1/admin/settings", json=changes, headers=admin)

    assert response.status_code == 422
    assert client.get("/api/v1/admin/settings", headers=admin).json() == before


def test_ratings_follow_the_setting(client: TestClient, admin: dict[str, str]) -> None:
    image_id = upload(client, admin, ["rating:nsfw"]).json()["id"]

    client.patch("/api/v1/admin/settings", json={"rating_values": ["safe", "explicit"]}, headers=admin)

    refused = upload(client, admin, ["rating:nsfw"], colour="red")
    assert (refused.status_code, refused.json()["code"]) == (422, "invalid_tag")
    assert client.get(f"/api/v1/images/{image_id}", headers=admin).json()["tags"] == ["rating:nsfw"]  # kept
    response = client.patch(f"/api/v1/images/{image_id}", json={"add_tags": ["rating:explicit"]}, headers=admin)
    assert response.json()["tags"] == ["rating:explicit"]
