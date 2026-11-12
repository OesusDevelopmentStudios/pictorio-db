# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/auth: logging in and out of a device, and who is logged in."""

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import AccessServiceDependency, AuthServiceDependency, CurrentAuthentication
from pictorio_db.services.auth import PASSWORD_MAX_LENGTH, Role, TokenInfo, UserInfo
from pictorio_db.utils.problems import problem_responses
from pictorio_db.utils.time import as_utc

DEVICE_NAME_MAX_LENGTH = 100

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=PASSWORD_MAX_LENGTH)
    device_name: str = Field(min_length=1, max_length=DEVICE_NAME_MAX_LENGTH, examples=["laptop (pictorio 0.1.0)"])


class UserSummary(BaseModel):
    id: int
    username: str
    role: Role


class CreatedToken(BaseModel):
    token_id: int
    token: str = Field(description="Shown only in this response; the server keeps just its SHA-256")
    user: UserSummary


class CurrentUser(UserSummary):
    restricted_tags: list[str] = Field(description="Terms an admin has restricted for this user; [] if none")


class DeviceToken(BaseModel):
    token_id: int
    device_name: str
    created_at: datetime
    last_used_at: datetime
    is_current: bool = Field(description="The token this request was sent with")


@router.post(
    "/tokens",
    status_code=status.HTTP_201_CREATED,
    summary="Log in a device and get its API token (public)",
    responses=problem_responses(401, 422, 429),
)
def create_token(login: LoginRequest, auth: AuthServiceDependency) -> CreatedToken:
    new_token = auth.create_token(login.username, login.password, login.device_name)
    return CreatedToken(token_id=new_token.info.id, token=new_token.token, user=_user_summary(new_token.user))


@router.get("/me", summary="The logged-in user", responses=problem_responses(401))
def current_user(authentication: CurrentAuthentication, access: AccessServiceDependency) -> CurrentUser:
    """restricted_tags lets the app warn before an upload or tag change would be refused; [] for admins."""
    user = authentication.user
    restricted_tags = [] if user.role == Role.ADMIN else access.restricted_terms(user.id)
    return CurrentUser(id=user.id, username=user.username, role=user.role, restricted_tags=restricted_tags)


@router.get("/tokens", summary="The logged-in user's devices", responses=problem_responses(401))
def list_tokens(authentication: CurrentAuthentication, auth: AuthServiceDependency) -> list[DeviceToken]:
    return [_device_token(token, authentication.token_id) for token in auth.list_tokens(authentication.user.id)]


@router.delete(
    "/tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke one of your tokens; revoking the current one logs out",
    responses=problem_responses(401, 404, 422),
)
def revoke_token(token_id: int, authentication: CurrentAuthentication, auth: AuthServiceDependency) -> None:
    auth.revoke_token(authentication.user.id, token_id)


def _user_summary(user: UserInfo) -> UserSummary:
    return UserSummary(id=user.id, username=user.username, role=user.role)


def _device_token(token: TokenInfo, current_token_id: int) -> DeviceToken:
    return DeviceToken(
        token_id=token.id,
        device_name=token.device_name,
        created_at=as_utc(token.created_at),
        last_used_at=as_utc(token.last_used_at),
        is_current=token.id == current_token_id,
    )
