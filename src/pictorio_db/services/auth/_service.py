# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pictorio_db.db import Database
from pictorio_db.db.models import ApiToken, User
from pictorio_db.services.auth._login_attempts import LoginAttempts
from pictorio_db.services.auth._passwords import hash_password, needs_rehash, verify_password
from pictorio_db.services.auth._setup_code import generate_setup_code, setup_codes_match
from pictorio_db.services.auth._tokens import generate_token, token_sha256
from pictorio_db.services.auth._validation import check_password, check_username, normalized_username
from pictorio_db.utils.problems import Problem
from pictorio_db.utils.time import utc_now


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


@dataclass(frozen=True)
class UserInfo:
    id: int
    username: str
    role: Role
    created_at: datetime


@dataclass(frozen=True)
class TokenInfo:
    id: int
    device_name: str
    created_at: datetime
    last_used_at: datetime


@dataclass(frozen=True)
class NewToken:
    token: str  # the only time the token itself is available; the server keeps just its SHA-256
    info: TokenInfo
    user: UserInfo


@dataclass(frozen=True)
class Authentication:
    user: UserInfo
    token_id: int


class AuthService:
    """User accounts, logins (API tokens) and the one-time setup of the first admin account."""

    def __init__(self, database: Database, now: Callable[[], datetime] = utc_now) -> None:
        self._database = database
        self._now = now
        self._login_attempts = LoginAttempts()
        self._setup_code: str | None = None

    # --- First admin account

    def is_setup_required(self) -> bool:
        with self._database.session() as session:
            return self._admin_count(session) == 0

    def setup_code(self) -> str | None:
        """The code that /admin/setup asks for, while no admin exists. Lives only in memory: a restart
        prints a new one."""
        if not self.is_setup_required():
            return None

        if self._setup_code is None:
            self._setup_code = generate_setup_code()

        return self._setup_code

    def complete_setup(self, entered_code: str, username: str, password: str) -> UserInfo:
        expected_code = self.setup_code()
        if expected_code is None:
            raise Problem(409, "setup_done", "Setup is already done", "An admin account exists already.")

        if not setup_codes_match(expected_code, entered_code):
            raise Problem(403, "wrong_setup_code", "Wrong setup code", "The code is in the server log.")

        user = self.create_user(username, password, Role.ADMIN)
        self._setup_code = None
        return user

    # --- Users

    def create_user(self, username: str, password: str, role: Role) -> UserInfo:
        username = normalized_username(username)
        check_username(username)
        check_password(password)
        user = User(username=username, password_hash=hash_password(password), role=role, created_at=self._now())
        with self._database.session() as session:
            session.add(user)
            try:
                session.commit()
            except IntegrityError:
                raise Problem(
                    409, "already_exists", "Username is taken", f"A user {username!r} exists already."
                ) from None

            return _user_info(user)

    # --- Logins

    def create_token(self, username: str, password: str, device_name: str) -> NewToken:
        """Logs in one device. Wrong username and wrong password give the same answer."""
        username = normalized_username(username)
        now = self._now()
        retry_after = self._login_attempts.seconds_until_allowed(username, now)
        if retry_after is not None:
            raise Problem(
                429,
                "too_many_attempts",
                "Too many failed logins",
                "Wait before trying again.",
                headers={"Retry-After": str(retry_after)},
            )

        with self._database.session() as session:
            user = session.scalars(select(User).where(User.username == username)).one_or_none()
            if not verify_password(user.password_hash if user else None, password):
                self._login_attempts.record_failure(username, now)
                raise not_authenticated()

            self._login_attempts.clear(username)
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)

            token = generate_token()
            api_token = ApiToken(
                user_id=user.id,
                token_sha256=token_sha256(token),
                device_name=device_name,
                created_at=now,
                last_used_at=now,
            )
            session.add(api_token)
            session.commit()
            return NewToken(token=token, info=_token_info(api_token), user=_user_info(user))

    def authenticate(self, token: str) -> Authentication:
        """The user a token belongs to. Raises 401 for an unknown or revoked token."""
        with self._database.session() as session:
            api_token = session.scalars(
                select(ApiToken).where(ApiToken.token_sha256 == token_sha256(token))
            ).one_or_none()
            if api_token is None:
                raise not_authenticated()

            api_token.last_used_at = self._now()
            user = session.get_one(User, api_token.user_id)
            session.commit()
            return Authentication(user=_user_info(user), token_id=api_token.id)

    def list_tokens(self, user_id: int) -> list[TokenInfo]:
        with self._database.session() as session:
            api_tokens = session.scalars(
                select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.created_at, ApiToken.id)
            )
            return [_token_info(api_token) for api_token in api_tokens]

    def revoke_token(self, user_id: int, token_id: int) -> None:
        """Only the user's own tokens; another user's token behaves as if it did not exist."""
        with self._database.session() as session:
            result = session.execute(delete(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id))
            session.commit()

        if result.rowcount == 0:
            raise Problem(404, "not_found", "Token not found")

    @staticmethod
    def _admin_count(session: Session) -> int:
        return session.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN)) or 0


def not_authenticated() -> Problem:
    return Problem(
        401,
        "not_authenticated",
        "Not authenticated",
        "Wrong username or password, or the token is unknown or revoked.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _user_info(user: User) -> UserInfo:
    return UserInfo(id=user.id, username=user.username, role=Role(user.role), created_at=user.created_at)


def _token_info(api_token: ApiToken) -> TokenInfo:
    return TokenInfo(
        id=api_token.id,
        device_name=api_token.device_name,
        created_at=api_token.created_at,
        last_used_at=api_token.last_used_at,
    )
