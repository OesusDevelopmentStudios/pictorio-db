# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What the routers need from the app: the services, and the user who sent the request."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pictorio_db.services.auth import Authentication, AuthService, Role, not_authenticated
from pictorio_db.services.images import ImagesService
from pictorio_db.services.importer import ImporterService
from pictorio_db.services.preferences import PreferencesService
from pictorio_db.services.search import SearchService
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

# auto_error=False: a missing token is answered with our own 401 problem, not FastAPI's error.
_bearer_token = HTTPBearer(auto_error=False, description="An API token from POST /api/v1/auth/tokens")


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def tags_service(request: Request) -> TagsService:
    return request.app.state.tags


def images_service(request: Request) -> ImagesService:
    return request.app.state.images


def importer_service(request: Request) -> ImporterService:
    return request.app.state.importer


def preferences_service(request: Request) -> PreferencesService:
    return request.app.state.preferences


def search_service(request: Request) -> SearchService:
    return request.app.state.search


def storage_service(request: Request) -> StorageService:
    return request.app.state.storage


def thumbnails_service(request: Request) -> ThumbnailsService:
    return request.app.state.thumbnails


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
TagsServiceDependency = Annotated[TagsService, Depends(tags_service)]
ImagesServiceDependency = Annotated[ImagesService, Depends(images_service)]
ImporterServiceDependency = Annotated[ImporterService, Depends(importer_service)]
PreferencesServiceDependency = Annotated[PreferencesService, Depends(preferences_service)]
SearchServiceDependency = Annotated[SearchService, Depends(search_service)]
StorageServiceDependency = Annotated[StorageService, Depends(storage_service)]
ThumbnailsServiceDependency = Annotated[ThumbnailsService, Depends(thumbnails_service)]
CurrentAuthentication = Annotated[Authentication, Depends(current_authentication)]
CurrentAdmin = Annotated[Authentication, Depends(current_admin)]
