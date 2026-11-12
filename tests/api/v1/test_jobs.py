# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Jobs over the API: reading them, and starting folder imports."""

import dataclasses
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from pictorio_db.app import create_app
from pictorio_db.config import Config
from pictorio_db.services.auth import Role
from pictorio_db.services.jobs import JobContext, JobKind

PASSWORD = "correct horse battery"
TEST_KIND = JobKind.REBUILD_THUMBNAILS


def log_in(client: TestClient, username: str, role: Role) -> tuple[dict[str, str], int]:
    user = client.app.state.auth.create_user(username, PASSWORD, role)
    login = {"username": username, "password": PASSWORD, "device_name": "t"}
    token = client.post("/api/v1/auth/tokens", json=login).json()["token"]
    return {"Authorization": f"Bearer {token}"}, user.id


def count_items(context: JobContext) -> dict[str, Any]:
    total = context.params["items"]
    for item in range(total):
        context.report_progress(item + 1, total)

    return {"counted": total}


@pytest.fixture
def kid(client: TestClient) -> tuple[dict[str, str], int]:
    return log_in(client, "kid", Role.USER)


def wait_for_job(client: TestClient, headers: dict[str, str], job_id: int) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}", headers=headers).json()
        if job["status"] in ("done", "failed"):
            return job

        time.sleep(0.01)

    raise AssertionError(f"Job {job_id} did not finish in time")


def test_jobs_need_a_login(client: TestClient) -> None:
    assert client.get("/api/v1/jobs").status_code == 401
    assert client.get("/api/v1/jobs/1").status_code == 401


def test_shows_a_finished_job(client: TestClient, kid: tuple[dict[str, str], int]) -> None:
    headers, kid_id = kid
    client.app.state.jobs.register(TEST_KIND, count_items)
    job_id = client.app.state.jobs.submit(TEST_KIND, {"items": 2}, kid_id).id

    job = wait_for_job(client, headers, job_id)

    assert job["status"] == "done"
    assert (job["kind"], job["params"], job["result"], job["error"]) == (TEST_KIND, {"items": 2}, {"counted": 2}, None)
    assert (job["progress_done"], job["progress_total"], job["created_by"]) == (2, 2, kid_id)
    assert job["created_at"].endswith("Z") and job["finished_at"].endswith("Z")


def test_other_users_jobs_are_not_found(client: TestClient, kid: tuple[dict[str, str], int]) -> None:
    headers, _kid_id = kid
    admin_headers, admin_id = log_in(client, "apo", Role.ADMIN)
    admins_job = client.app.state.jobs.submit(TEST_KIND, {}, admin_id).id

    response = client.get(f"/api/v1/jobs/{admins_job}", headers=headers)

    assert (response.status_code, response.json()["code"]) == (404, "not_found")
    assert client.get("/api/v1/jobs", headers=headers).json() == []
    assert [job["id"] for job in client.get("/api/v1/jobs", headers=admin_headers).json()] == [admins_job]


def test_lists_jobs_by_status(client: TestClient, kid: tuple[dict[str, str], int]) -> None:
    headers, kid_id = kid
    client.app.state.jobs.register(TEST_KIND, count_items)
    done = client.app.state.jobs.submit(TEST_KIND, {"items": 1}, kid_id).id
    wait_for_job(client, headers, done)

    def listed(status: str) -> list[int]:
        return [job["id"] for job in client.get("/api/v1/jobs", params={"status": status}, headers=headers).json()]

    assert (listed("done"), listed("failed")) == ([done], [])
    assert client.get("/api/v1/jobs", params={"status": "paused"}, headers=headers).status_code == 422


# --- Folder imports

@pytest.fixture
def import_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "import"
    (folder / "trip").mkdir(parents=True)
    Image.new("RGB", (8, 8), "blue").save(folder / "trip" / "beach.jpg", format="JPEG")
    return folder


@pytest.fixture
def importing_client(config: Config, import_dir: Path) -> Iterator[TestClient]:
    with TestClient(create_app(dataclasses.replace(config, import_dir=import_dir))) as started_client:
        yield started_client


def test_admin_imports_a_folder(importing_client: TestClient) -> None:
    headers, _admin_id = log_in(importing_client, "apo", Role.ADMIN)
    body = {"source_subdir": "trip", "tags": ["album:trip"]}

    response = importing_client.post("/api/v1/admin/import-jobs", json=body, headers=headers)

    assert response.status_code == 202
    job = wait_for_job(importing_client, headers, response.json()["job_id"])
    assert (job["kind"], job["status"]) == ("folder_import", "done")
    assert job["params"] == {"source_subdir": "trip", "remove_originals": False, "tags": ["album:trip"]}
    assert job["result"] == {"imported": 1, "duplicates": 0, "unsupported": 0, "failed": []}
    images = importing_client.get("/api/v1/images", params={"q": "album:trip"}, headers=headers).json()["items"]
    assert len(images) == 1


def test_only_admins_import_folders(importing_client: TestClient) -> None:
    headers, _kid_id = log_in(importing_client, "kid", Role.USER)

    response = importing_client.post("/api/v1/admin/import-jobs", json={"source_subdir": "trip"}, headers=headers)

    assert response.status_code == 403


def test_path_outside_the_import_folder_is_refused(importing_client: TestClient) -> None:
    headers, _admin_id = log_in(importing_client, "apo", Role.ADMIN)

    response = importing_client.post("/api/v1/admin/import-jobs", json={"source_subdir": ".."}, headers=headers)

    assert (response.status_code, response.json()["title"]) == (422, "Invalid folder")
    assert importing_client.get("/api/v1/jobs", headers=headers).json() == []


def test_folder_imports_are_off_without_an_import_folder(client: TestClient) -> None:
    headers, _admin_id = log_in(client, "apo", Role.ADMIN)

    response = client.post("/api/v1/admin/import-jobs", json={"source_subdir": ""}, headers=headers)

    assert (response.status_code, response.json()["code"]) == (409, "import_dir_not_set")
