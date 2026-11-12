# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Admin logins in the browser: a token like the desktop app's, kept in a cookie, and a CSRF token on every
form. The cookie is HttpOnly (scripts cannot read it) and SameSite=Strict (other sites cannot send it)."""

import hashlib
import hmac
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from pictorio_db.admin_web._templates import templates
from pictorio_db.services.auth import AuthService, Role, UserInfo
from pictorio_db.utils.problems import Problem

COOKIE_NAME = "pictorio_admin"
SESSION_LIFETIME = timedelta(hours=12)
DEVICE_NAME = "Web admin"


@dataclass(frozen=True)
class AdminSession:
    user: UserInfo
    token_id: int
    csrf_token: str  # goes into every form


class LoginRequired(Exception):
    def __init__(self, return_to: str | None) -> None:
        super().__init__("Login required")
        self.return_to = return_to


class PageError(Exception):
    """Shown as a page of its own, for errors no form can show."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def install_page_handlers(app: FastAPI) -> None:
    async def redirect_to_login(_request: Request, error: LoginRequired) -> RedirectResponse:
        target = "/admin/login" if error.return_to is None else f"/admin/login?next={quote(error.return_to)}"
        return RedirectResponse(target, status_code=303)

    async def error_page(request: Request, error: PageError) -> HTMLResponse:
        context = {"message": error.message}
        return templates.TemplateResponse(request, "error.html", context, status_code=error.status_code)

    app.add_exception_handler(LoginRequired, redirect_to_login)  # type: ignore[arg-type]
    app.add_exception_handler(PageError, error_page)  # type: ignore[arg-type]


def admin_session(request: Request) -> AdminSession:
    """Pages for admins: without a valid login, the browser is sent to the login page."""
    return_to = request.url.path if request.method == "GET" else None
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise LoginRequired(return_to)

    auth: AuthService = request.app.state.auth
    try:
        authentication = auth.authenticate(token)
    except Problem:
        raise LoginRequired(return_to) from None  # expired or logged out

    if authentication.user.role != Role.ADMIN:
        raise LoginRequired(return_to)  # no longer an admin

    return AdminSession(authentication.user, authentication.token_id, csrf_token_for(token))


def checked_form_session(
    session: Annotated[AdminSession, Depends(admin_session)], csrf_token: Annotated[str, Form()] = ""
) -> AdminSession:
    """Forms that change something: the CSRF token proves the form came from these pages."""
    if not hmac.compare_digest(csrf_token, session.csrf_token):
        raise PageError(403, "This form has expired. Go back, reload the page and try again.")

    return session


AdminPage = Annotated[AdminSession, Depends(admin_session)]
AdminForm = Annotated[AdminSession, Depends(checked_form_session)]


def csrf_token_for(session_token: str) -> str:
    """Derived from the session token, which only the logged-in browser has; nothing more to store."""
    return hashlib.sha256(f"csrf:{session_token}".encode()).hexdigest()


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    """No expiry date, so the browser forgets it when it closes; the server ends it after SESSION_LIFETIME."""
    response.set_cookie(
        COOKIE_NAME,
        token,
        path="/admin",
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/admin", httponly=True, samesite="strict")
