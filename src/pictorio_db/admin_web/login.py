# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin/login and /admin/logout: admin logins in the browser."""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from pictorio_db.admin_web._session import (
    DEVICE_NAME,
    SESSION_LIFETIME,
    AdminForm,
    LoginRequired,
    admin_session,
    clear_session_cookie,
    set_session_cookie,
)
from pictorio_db.admin_web._templates import templates
from pictorio_db.services.auth import AuthService
from pictorio_db.utils.problems import Problem

router = APIRouter()

_LOGIN_MESSAGES = {
    "not_authenticated": "Wrong username or password.",
    "forbidden": "Only admins can use these pages.",
    "too_many_attempts": "Too many failed logins. Wait a few minutes, then try again.",
}


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/admin") -> Response:
    try:
        admin_session(request)
        return RedirectResponse(_safe_return_path(next), status_code=303)  # logged in already
    except LoginRequired:
        return _login_page(request, next)


@router.post("/login", response_class=HTMLResponse)
def log_in(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/admin",
) -> Response:
    try:
        new_token = _auth(request).create_token(
            username, password, DEVICE_NAME, lifetime=SESSION_LIFETIME, admins_only=True
        )
    except Problem as problem:
        error = _LOGIN_MESSAGES.get(problem.code, f"{problem.title}. {problem.detail or ''}".strip())
        return _login_page(request, next, username, error, problem.status)

    response = RedirectResponse(_safe_return_path(next), status_code=303)
    set_session_cookie(response, request, new_token.token)
    return response


@router.post("/logout")
def log_out(request: Request, session: AdminForm) -> RedirectResponse:
    _auth(request).revoke_token(session.user.id, session.token_id)
    response = RedirectResponse("/admin/login", status_code=303)
    clear_session_cookie(response)
    return response


def _auth(request: Request) -> AuthService:
    return request.app.state.auth


def _login_page(
    request: Request, next: str, username: str = "", error: str | None = None, status_code: int = 200
) -> HTMLResponse:
    context = {
        "next": _safe_return_path(next),
        "username": username,
        "error": error,
        "setup_required": _auth(request).is_setup_required(),
    }
    return templates.TemplateResponse(request, "login.html", context, status_code=status_code)


def _safe_return_path(path: str) -> str:
    """Only back to an admin page, never to another site."""
    return path if path.startswith("/admin") and "//" not in path and "\\" not in path else "/admin"
