# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin: server administration, for admins only."""

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import (
    AccessServiceDependency,
    AuthServiceDependency,
    CurrentAdmin,
    FolderImportDependency,
    ServerSettingsDependency,
)
from pictorio_db.services.auth import PASSWORD_MAX_LENGTH, Role, UserInfo
from pictorio_db.services.importer import UPLOAD_LIMIT_RANGE
from pictorio_db.services.server_settings import ServerSettingsInfo, SettingsChanges
from pictorio_db.services.tags import MAX_RATING_VALUES
from pictorio_db.utils.problems import problem_responses
from pictorio_db.utils.time import as_utc

router = APIRouter(prefix="/admin", tags=["admin"])


class UserDetails(BaseModel):
    id: int
    username: str
    role: Role
    restricted_tags: list[str] = Field(description="Terms this user may not see or use; [] if none")
    restrictions_active: bool = Field(description="False for admins: they are never restricted")
    created_at: datetime


RESTRICTED_TAGS_DESCRIPTION = "Search terms, e.g. rating:nsfw or character:*; ignored for admins"


class NewUser(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    role: Role
    restricted_tags: list[str] = Field(default=[], max_length=100, description=RESTRICTED_TAGS_DESCRIPTION)


class UserChanges(BaseModel):
    password: str | None = Field(default=None, max_length=PASSWORD_MAX_LENGTH,
                                 description="A new password also logs the user out on every device")
    role: Role | None = None
    restricted_tags: list[str] | None = Field(
        default=None, max_length=100, description=f"Replaces the whole list. {RESTRICTED_TAGS_DESCRIPTION}"
    )


@router.get("/users", summary="All user accounts", responses=problem_responses(401, 403))
def list_users(
    _admin: CurrentAdmin, auth: AuthServiceDependency, access: AccessServiceDependency
) -> list[UserDetails]:
    return [_user_details(user, access) for user in auth.list_users()]


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account",
    responses=problem_responses(401, 403, 409, 422),
)
def create_user(
    new_user: NewUser, _admin: CurrentAdmin, auth: AuthServiceDependency, access: AccessServiceDependency
) -> UserDetails:
    restricted_tags = access.checked_terms(new_user.restricted_tags)  # before anything is created
    user = auth.create_user(new_user.username, new_user.password, new_user.role)
    access.set_restricted_terms(user.id, restricted_tags)
    return _user_details(user, access)


@router.patch(
    "/users/{user_id}",
    summary="Change a user's password, role or restricted tags",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def update_user(
    user_id: int,
    changes: UserChanges,
    _admin: CurrentAdmin,
    auth: AuthServiceDependency,
    access: AccessServiceDependency,
) -> UserDetails:
    restricted_tags = None if changes.restricted_tags is None else access.checked_terms(changes.restricted_tags)
    user = auth.update_user(user_id, password=changes.password, role=changes.role)
    if restricted_tags is not None:
        access.set_restricted_terms(user.id, restricted_tags)

    return _user_details(user, access)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user account; the last admin cannot be deleted",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def delete_user(user_id: int, _admin: CurrentAdmin, auth: AuthServiceDependency) -> None:
    auth.delete_user(user_id)


class Settings(BaseModel):
    path_template: str = Field(
        description="Where images are stored in the library: folders named by {namespace} placeholders and "
        "{year} and {month}",
        examples=["{category}/{author}/{year}"],
    )
    max_upload_bytes: int
    rating_values: list[str] = Field(description="The only values a rating: tag may have", examples=[["sfw", "nsfw"]])
    library_dir: str = Field(description="Read-only: set with PICTORIO_LIBRARY_DIR")
    import_dir: str | None = Field(
        description="Read-only: set with PICTORIO_IMPORT_DIR; null if folder imports are off"
    )


class ChangedSettings(Settings):
    job_id: int | None = Field(description="The job that moves the files after a new path_template; else null")


class SettingsChangeRequest(BaseModel):
    """Only the settings given are changed."""

    path_template: str | None = Field(
        default=None, max_length=1000, description="A different template starts a job that moves every file"
    )
    max_upload_bytes: int | None = Field(default=None, ge=UPLOAD_LIMIT_RANGE[0], le=UPLOAD_LIMIT_RANGE[1])
    rating_values: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_RATING_VALUES,
        description="Images keep a rating that is removed here, but it cannot be given again",
    )


@router.get("/settings", summary="The server's settings", responses=problem_responses(401, 403))
def get_settings(_admin: CurrentAdmin, server_settings: ServerSettingsDependency) -> Settings:
    return Settings(**_settings_fields(server_settings.current()))


@router.patch(
    "/settings",
    summary="Change the server's settings; a new path template moves the files in the background",
    responses=problem_responses(401, 403, 422),
)
def change_settings(
    request: SettingsChangeRequest, admin: CurrentAdmin, server_settings: ServerSettingsDependency
) -> ChangedSettings:
    changes = SettingsChanges(request.path_template, request.max_upload_bytes, request.rating_values)
    settings, job = server_settings.change(changes, admin.user.id)
    return ChangedSettings(**_settings_fields(settings), job_id=None if job is None else job.id)


def _settings_fields(settings: ServerSettingsInfo) -> dict[str, object]:
    return {
        "path_template": settings.path_template,
        "max_upload_bytes": settings.max_upload_bytes,
        "rating_values": settings.rating_values,
        "library_dir": str(settings.library_dir),
        "import_dir": None if settings.import_dir is None else str(settings.import_dir),
    }


class ImportRequest(BaseModel):
    source_subdir: str = Field(
        max_length=1000,
        description="A folder inside the server's import folder (PICTORIO_IMPORT_DIR); '' for all of it",
        examples=["phone_backup/2025"],
    )
    remove_originals: bool = Field(
        default=False, description="Delete each file once it is in the library, or was there already"
    )
    tags: list[str] = Field(default=[], max_length=200, description="Given to every imported image")


class StartedJob(BaseModel):
    job_id: int = Field(description="Follow its progress at /api/v1/jobs/{job_id}")


@router.post(
    "/import-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Import a folder on the server, in the background",
    responses=problem_responses(401, 403, 409, 422),
)
def start_import(request: ImportRequest, admin: CurrentAdmin, folder_import: FolderImportDependency) -> StartedJob:
    job = folder_import.start(request.source_subdir, request.remove_originals, request.tags, admin.user.id)
    return StartedJob(job_id=job.id)


def _user_details(user: UserInfo, access: AccessServiceDependency) -> UserDetails:
    return UserDetails(
        id=user.id,
        username=user.username,
        role=user.role,
        restricted_tags=access.restricted_terms(user.id),
        restrictions_active=user.role == Role.USER,
        created_at=as_utc(user.created_at),
    )
