# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What the routers need from the app: the services, and the user who sent the request."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pictorio_db.services.auth import Authentication, AuthService, not_authenticated

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


AuthServiceDependency = Annotated[AuthService, Depends(auth_service)]
CurrentAuthentication = Annotated[Authentication, Depends(current_authentication)]
