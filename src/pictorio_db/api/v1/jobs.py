# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/jobs: long tasks that run in the background, such as a folder import. Clients poll them."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import CurrentAuthentication, JobsServiceDependency
from pictorio_db.services.jobs import LIST_LIMIT, JobInfo, JobKind, JobStatus
from pictorio_db.utils.problems import problem_responses
from pictorio_db.utils.time import as_utc

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobDetails(BaseModel):
    id: int
    kind: JobKind
    status: JobStatus
    params: dict[str, Any] = Field(description="What the job was asked to do; depends on its kind")
    progress_done: int
    progress_total: int | None = Field(description="null while the job does not know yet")
    result: dict[str, Any] | None = Field(description="Counts of what was done, once the job is done")
    error: str | None = Field(description="Why the job failed, once it has")
    created_by: int | None = Field(description="The user who started the job; null for the server itself")
    created_at: datetime
    finished_at: datetime | None


@router.get(
    "",
    summary=f"Your latest jobs, newest first, at most {LIST_LIMIT}; admins see everyone's",
    responses=problem_responses(401, 422),
)
def list_jobs(
    authentication: CurrentAuthentication, jobs: JobsServiceDependency, status: JobStatus | None = None
) -> list[JobDetails]:
    return [_job_details(job) for job in jobs.list_jobs(authentication.user, status)]


@router.get("/{job_id}", summary="One job and its progress", responses=problem_responses(401, 404))
def get_job(job_id: int, authentication: CurrentAuthentication, jobs: JobsServiceDependency) -> JobDetails:
    return _job_details(jobs.get_job(job_id, authentication.user))


def _job_details(job: JobInfo) -> JobDetails:
    return JobDetails(
        id=job.id,
        kind=JobKind(job.kind),
        status=job.status,
        params=job.params,
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        result=job.result,
        error=job.error,
        created_by=job.created_by,
        created_at=as_utc(job.created_at),
        finished_at=as_utc(job.finished_at) if job.finished_at is not None else None,
    )
