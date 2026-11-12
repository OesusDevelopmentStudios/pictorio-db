# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin: server administration, for admins only."""

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import AccessServiceDependency, AuthServiceDependency, CurrentAdmin
from pictorio_db.services.auth import PASSWORD_MAX_LENGTH, Role, UserInfo
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


def _user_details(user: UserInfo, access: AccessServiceDependency) -> UserDetails:
    return UserDetails(
        id=user.id,
        username=user.username,
        role=user.role,
        restricted_tags=access.restricted_terms(user.id),
        restrictions_active=user.role == Role.USER,
        created_at=as_utc(user.created_at),
    )
