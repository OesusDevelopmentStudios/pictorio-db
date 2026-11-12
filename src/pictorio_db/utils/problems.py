# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Errors as RFC 9457 Problem Details. Clients branch on the stable `code`, never on `title`."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"

# The reserved .invalid domain, until the project has a documentation URL
PROBLEM_TYPE_BASE = "https://pictorio.invalid/problems/"

# Codes for the HTTP errors that FastAPI and Starlette raise themselves, e.g. for an unknown path
_CODES_FOR_HTTP_STATUS = {
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}

_logger = logging.getLogger(__name__)


class ProblemModel(BaseModel):
    """How a problem looks, for the API documentation. Some codes add fields of their own."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None


class FieldError(BaseModel):
    field: str
    message: str


class ValidationProblemModel(ProblemModel):
    errors: list[FieldError]


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Documents the given error statuses of an endpoint as problem responses."""
    return {
        status: {
            "model": ValidationProblemModel if status == 422 else ProblemModel,
            "content": {PROBLEM_MEDIA_TYPE: {}},
            "description": "Problem details (RFC 9457)",
        }
        for status in statuses
    }


class Problem(Exception):
    """Raise anywhere to answer with a problem response. `extra` adds code-specific fields,
    e.g. existing_image_id."""

    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers
        self.extra = extra


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _handle_problem)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
    _document_problems_with_their_media_type(app)


# FastAPI documents every response schema under application/json. Problems are sent as
# application/problem+json, so their schema is moved there.
def _document_problems_with_their_media_type(app: FastAPI) -> None:
    generate_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = generate_openapi()  # FastAPI caches it, so this runs once in effect
        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                for response in operation.get("responses", {}).values():
                    content = response.get("content", {})
                    if PROBLEM_MEDIA_TYPE in content and "application/json" in content:
                        content[PROBLEM_MEDIA_TYPE] = content.pop("application/json")

        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def problem_response(problem: Problem) -> JSONResponse:
    body = {
        "type": PROBLEM_TYPE_BASE + problem.code.replace("_", "-"),
        "title": problem.title,
        "status": problem.status,
        "code": problem.code,
    }
    if problem.detail is not None:
        body["detail"] = problem.detail

    body.update(problem.extra)
    return JSONResponse(body, status_code=problem.status, headers=problem.headers, media_type=PROBLEM_MEDIA_TYPE)


async def _handle_problem(_request: Request, problem: Problem) -> JSONResponse:
    return problem_response(problem)


async def _handle_http_exception(_request: Request, error: StarletteHTTPException) -> JSONResponse:
    code = _CODES_FOR_HTTP_STATUS.get(error.status_code, f"http_{error.status_code}")
    title = str(error.detail)
    return problem_response(Problem(error.status_code, code, title, headers=error.headers))


async def _handle_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": ".".join(str(part) for part in validation_error["loc"]), "message": validation_error["msg"]}
        for validation_error in error.errors()
    ]
    return problem_response(
        Problem(422, "validation_error", "Invalid request", "The request body or parameters are invalid.",
                errors=errors)
    )


# The client gets an id to report, and the full trace goes to the log under that id.
async def _handle_unexpected_error(_request: Request, error: Exception) -> JSONResponse:
    trace_id = uuid.uuid4().hex
    _logger.error("Unexpected error, trace id %s", trace_id, exc_info=error)
    return problem_response(
        Problem(500, "internal_error", "Internal server error", "The server failed unexpectedly.", trace_id=trace_id)
    )
