# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What the routers need from the app: the services, and the user who sent the request."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pictorio_db.services.auth import Authentication, AuthService, Role, not_authenticated
from pictorio_db.utils.problems import Problem

# auto_error=False: a missing token is answered with our own 401 problem, not FastAPI's error.
_bearer_token = HTTPBearer(auto_error=False, description="An API token from POST /api/v1/auth/tokens")


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def current_authentication(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_token)],
    auth: Annotated[AuthService, Depends(auth_service)],
) -> Authentication:
    """Protects an endpoint: the request needs `Authorization: Bearer <token>`, or it gets 401."""
    if credentials is None:
        raise not_authenticated()

    return auth.authenticate(credentials.credentials)


def current_admin(authentication: Annotated[Authentication, Depends(current_authentication)]) -> Authentication:
    """Protects an admin endpoint: other users get 403."""
    if authentication.user.role != Role.ADMIN:
        raise Problem(403, "forbidden", "Admins only", "This needs an admin account.")

    return authentication


AuthServiceDependency = Annotated[AuthService, Depends(auth_service)]
CurrentAuthentication = Annotated[Authentication, Depends(current_authentication)]
CurrentAdmin = Annotated[Authentication, Depends(current_admin)]
