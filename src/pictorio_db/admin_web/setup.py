# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin/setup: creates the first admin account with the one-time code from the server log."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from pictorio_db.admin_web._templates import templates
from pictorio_db.services.auth import PASSWORD_MIN_LENGTH, AuthService
from pictorio_db.utils.problems import Problem

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request) -> HTMLResponse:
    if not _auth(request).is_setup_required():
        return _done_page(request, created_username=None)

    return _form_page(request)


@router.post("/setup", response_class=HTMLResponse)
def complete_setup(
    request: Request,
    setup_code: Annotated[str, Form()],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_repeated: Annotated[str, Form()],
) -> HTMLResponse:
    if password != password_repeated:
        return _form_page(request, username, error="The two passwords differ.", status_code=422)

    try:
        admin = _auth(request).complete_setup(setup_code, username, password)
    except Problem as problem:
        if problem.code == "setup_done":
            return _done_page(request, created_username=None, status_code=problem.status)

        return _form_page(request, username, error=_message(problem), status_code=problem.status)

    return _done_page(request, created_username=admin.username)


def _auth(request: Request) -> AuthService:
    return request.app.state.auth


def _form_page(request: Request, username: str = "", error: str | None = None, status_code: int = 200) -> HTMLResponse:
    context = {"username": username, "error": error, "password_min_length": PASSWORD_MIN_LENGTH}
    return templates.TemplateResponse(request, "setup.html", context, status_code=status_code)


def _done_page(request: Request, created_username: str | None, status_code: int = 200) -> HTMLResponse:
    context = {"created_username": created_username}
    return templates.TemplateResponse(request, "setup_done.html", context, status_code=status_code)


def _message(problem: Problem) -> str:
    """A sentence for the page. Validation problems say which field is wrong and why."""
    if problem.code == "validation_error":
        field_errors = problem.extra.get("errors", [])
        return " ".join(f"{error['field'].capitalize()}: {error['message']}." for error in field_errors)

    return f"{problem.title}. {problem.detail or ''}".strip()
