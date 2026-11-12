# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select, update

from pictorio_db.db import Database
from pictorio_db.db.models import Job
from pictorio_db.services.auth import Role, UserInfo
from pictorio_db.utils.problems import Problem
from pictorio_db.utils.time import utc_now

PROGRESS_INTERVAL_SECONDS = 1.0  # progress is written at most this often
IDLE_WAIT_SECONDS = 5.0  # how long the worker sleeps when there is nothing to do, unless woken
LIST_LIMIT = 100

_logger = logging.getLogger(__name__)


class JobKind(StrEnum):
    FOLDER_IMPORT = "folder_import"
    RELAYOUT = "relayout"
    TAG_RENAME = "tag_rename"
    TAG_DELETE = "tag_delete"
    REBUILD_THUMBNAILS = "rebuild_thumbnails"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class JobInfo:
    id: int
    kind: str
    status: JobStatus
    params: dict[str, Any]
    progress_done: int
    progress_total: int | None
    result: dict[str, Any] | None
    error: str | None
    created_by: int | None
    created_at: datetime  # UTC
    finished_at: datetime | None  # UTC


class StopRequested(Exception):
    """Raised by JobContext when the server is stopping; the job is run again after the next start."""


class JobContext:
    """What a running job gets: its parameters, a way to report progress, and a way to notice that the server
    is stopping. Jobs call report_progress between items, so they stop between items, never inside one."""

    def __init__(self, service: "JobsService", job_id: int, params: dict[str, Any], created_by: int | None) -> None:
        self.params = params
        self.created_by = created_by
        self._service = service
        self._job_id = job_id
        self._last_written = 0.0

    def report_progress(self, done: int, total: int | None) -> None:
        """Raises StopRequested if the server is stopping."""
        if self._service.stopping:
            raise StopRequested

        now = time.monotonic()
        if now - self._last_written >= PROGRESS_INTERVAL_SECONDS or done == total:
            self._service._write_progress(self._job_id, done, total)
            self._last_written = now


# A job's work: reads its parameters from the context and returns the result counts.
JobHandler = Callable[[JobContext], dict[str, Any]]


class JobsService:
    """Long tasks, one at a time, on a single background thread. Each job is a row in the job table; clients
    poll its progress. No external queue: one more service to run would be too much on a Raspberry Pi."""

    def __init__(self, database: Database) -> None:
        self._database = database
        self._handlers: dict[str, JobHandler] = {}
        self._wake_up = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def register(self, kind: JobKind, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    def start(self) -> None:
        """Jobs a restart interrupted are queued again: every job can safely run twice."""
        with self._database.session() as session:
            session.execute(update(Job).where(Job.status == JobStatus.RUNNING).values(status=JobStatus.QUEUED))
            session.commit()

        self._stop.clear()
        self._thread = threading.Thread(target=self._work, name="pictorio-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout_seconds: float = 30.0) -> None:
        """Asks the running job to stop after its current item and waits for the worker."""
        self._stop.set()
        self._wake_up.set()
        if self._thread is not None:
            self._thread.join(timeout_seconds)

    def submit(self, kind: JobKind, params: dict[str, Any], user_id: int | None) -> JobInfo:
        job = Job(
            kind=kind,
            status=JobStatus.QUEUED,
            params=params,
            progress_done=0,
            progress_total=None,
            created_by=user_id,
            created_at=utc_now(),
        )
        with self._database.session() as session:
            session.add(job)
            session.commit()
            info = _job_info(job)

        self._wake_up.set()
        return info

    def get_job(self, job_id: int, user: UserInfo) -> JobInfo:
        """A user sees only their own jobs; others are 404. Admins see all jobs."""
        with self._database.session() as session:
            job = session.get(Job, job_id)
            if job is None or (user.role != Role.ADMIN and job.created_by != user.id):
                raise Problem(404, "not_found", "Job not found")

            return _job_info(job)

    def list_jobs(self, user: UserInfo, status: JobStatus | None = None) -> list[JobInfo]:
        """Newest first, at most LIST_LIMIT."""
        query = select(Job).order_by(Job.id.desc()).limit(LIST_LIMIT)
        if user.role != Role.ADMIN:
            query = query.where(Job.created_by == user.id)

        if status is not None:
            query = query.where(Job.status == status)

        with self._database.session() as session:
            return [_job_info(job) for job in session.scalars(query)]

    def _work(self) -> None:
        while not self._stop.is_set():
            if not self._run_next_job():
                self._wake_up.wait(IDLE_WAIT_SECONDS)
                self._wake_up.clear()

    def _run_next_job(self) -> bool:
        """Runs the oldest queued job. False if there was none."""
        job = self._claim_next_job()
        if job is None:
            return False

        handler = self._handlers.get(job.kind)
        try:
            if handler is None:
                raise Problem(500, "unknown_job", "Unknown job", f"No handler for jobs of kind {job.kind!r}.")

            result = handler(JobContext(self, job.id, job.params, job.created_by))
        except StopRequested:
            self._requeue(job.id)  # run again after the next start
            return True
        except Problem as problem:
            self._finish(job.id, JobStatus.FAILED, error=f"{problem.title}. {problem.detail or ''}".strip())
            return True
        except Exception:
            trace_id = uuid.uuid4().hex
            _logger.exception("Job %s failed, trace id %s", job.id, trace_id)
            self._finish(job.id, JobStatus.FAILED, error=f"Internal error; trace id {trace_id} in the server log")
            return True

        self._finish(job.id, JobStatus.DONE, result=result)
        return True

    def _claim_next_job(self) -> JobInfo | None:
        with self._database.session() as session:
            job = session.scalars(select(Job).where(Job.status == JobStatus.QUEUED).order_by(Job.id).limit(1)).first()
            if job is None:
                return None

            job.status = JobStatus.RUNNING
            session.commit()
            return _job_info(job)

    def _write_progress(self, job_id: int, done: int, total: int | None) -> None:
        with self._database.session() as session:
            session.execute(update(Job).where(Job.id == job_id).values(progress_done=done, progress_total=total))
            session.commit()

    def _requeue(self, job_id: int) -> None:
        with self._database.session() as session:
            session.execute(update(Job).where(Job.id == job_id).values(status=JobStatus.QUEUED))
            session.commit()

    def _finish(
        self, job_id: int, status: JobStatus, result: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        with self._database.session() as session:
            session.execute(
                update(Job)
                .where(Job.id == job_id)
                .values(status=status, result=result, error=error, finished_at=utc_now())
            )
            session.commit()


def _job_info(job: Job) -> JobInfo:
    return JobInfo(
        id=job.id,
        kind=job.kind,
        status=JobStatus(job.status),
        params=dict(job.params),
        progress_done=job.progress_done,
        progress_total=job.progress_total,
        result=job.result,
        error=job.error,
        created_by=job.created_by,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )
