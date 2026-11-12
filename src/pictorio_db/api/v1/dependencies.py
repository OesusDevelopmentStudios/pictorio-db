# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""What the routers need from the app: the services, and the user who sent the request."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pictorio_db.services.access import AccessService, Restrictions
from pictorio_db.services.auth import Authentication, AuthService, Role, not_authenticated
from pictorio_db.services.images import ImagesService
from pictorio_db.services.importer import ImporterService
from pictorio_db.services.jobs import FolderImport, JobsService
from pictorio_db.services.preferences import PreferencesService
from pictorio_db.services.search import SearchService
from pictorio_db.services.server_settings import ServerSettings
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tag_admin import TagAdmin
from pictorio_db.services.tags import TagsService
from pictorio_db.services.thumbnails import ThumbnailsService
from pictorio_db.utils.problems import Problem

# auto_error=False: a missing token is answered with our own 401 problem, not FastAPI's error.
_bearer_token = HTTPBearer(auto_error=False, description="An API token from POST /api/v1/auth/tokens")


def access_service(request: Request) -> AccessService:
    return request.app.state.access


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth


def tag_admin(request: Request) -> TagAdmin:
    return request.app.state.tag_admin


def tags_service(request: Request) -> TagsService:
    return request.app.state.tags


def images_service(request: Request) -> ImagesService:
    return request.app.state.images


def importer_service(request: Request) -> ImporterService:
    return request.app.state.importer


def folder_import(request: Request) -> FolderImport:
    return request.app.state.folder_import


def jobs_service(request: Request) -> JobsService:
    return request.app.state.jobs


def preferences_service(request: Request) -> PreferencesService:
    return request.app.state.preferences


def search_service(request: Request) -> SearchService:
    return request.app.state.search


def server_settings(request: Request) -> ServerSettings:
    return request.app.state.server_settings


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


def current_restrictions(
    authentication: Annotated[Authentication, Depends(current_authentication)],
    access: Annotated[AccessService, Depends(access_service)],
) -> Restrictions:
    """What the logged-in user may see and use; none for admins. Every image endpoint needs it."""
    return access.restrictions_for(authentication.user)


def current_admin(authentication: Annotated[Authentication, Depends(current_authentication)]) -> Authentication:
    """Protects an admin endpoint: other users get 403."""
    if authentication.user.role != Role.ADMIN:
        raise Problem(403, "forbidden", "Admins only", "This needs an admin account.")

    return authentication


AccessServiceDependency = Annotated[AccessService, Depends(access_service)]
AuthServiceDependency = Annotated[AuthService, Depends(auth_service)]
TagsServiceDependency = Annotated[TagsService, Depends(tags_service)]
TagAdminDependency = Annotated[TagAdmin, Depends(tag_admin)]
ImagesServiceDependency = Annotated[ImagesService, Depends(images_service)]
ImporterServiceDependency = Annotated[ImporterService, Depends(importer_service)]
JobsServiceDependency = Annotated[JobsService, Depends(jobs_service)]
FolderImportDependency = Annotated[FolderImport, Depends(folder_import)]
PreferencesServiceDependency = Annotated[PreferencesService, Depends(preferences_service)]
SearchServiceDependency = Annotated[SearchService, Depends(search_service)]
ServerSettingsDependency = Annotated[ServerSettings, Depends(server_settings)]
StorageServiceDependency = Annotated[StorageService, Depends(storage_service)]
ThumbnailsServiceDependency = Annotated[ThumbnailsService, Depends(thumbnails_service)]
CurrentAuthentication = Annotated[Authentication, Depends(current_authentication)]
CurrentAdmin = Annotated[Authentication, Depends(current_admin)]
CurrentRestrictions = Annotated[Restrictions, Depends(current_restrictions)]
