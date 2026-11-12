# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from pictorio_db.db import DATABASE_FILE_NAME, Database, open_database
from pictorio_db.db.models import ApiToken, User
from pictorio_db.services.auth import AuthService, Role
from pictorio_db.utils.problems import Problem

PASSWORD = "correct horse battery"


class TestClock:
    """Time that only moves when a test moves it."""

    __test__ = False  # not a test class for pytest

    def __init__(self) -> None:
        self.current = datetime(2026, 11, 12, 12, 0, 0)

    def now(self) -> datetime:
        return self.current

    def advance(self, duration: timedelta) -> None:
        self.current += duration


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    opened_database = open_database(tmp_path / DATABASE_FILE_NAME)
    yield opened_database
    opened_database.close()


@pytest.fixture
def clock() -> TestClock:
    return TestClock()


@pytest.fixture
def auth(database: Database, clock: TestClock) -> AuthService:
    return AuthService(database, now=clock.now)


def raised_problem(action: object) -> Problem:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]
    return raised.value


# --- First admin account

def test_setup_is_required_until_an_admin_exists(auth: AuthService) -> None:
    assert auth.is_setup_required()

    auth.create_user("kid", PASSWORD, Role.USER)
    assert auth.is_setup_required()  # a normal user is not enough

    auth.create_user("apo", PASSWORD, Role.ADMIN)
    assert not auth.is_setup_required()
    assert auth.setup_code() is None


def test_setup_code_is_readable_and_stays_the_same(auth: AuthService) -> None:
    code = auth.setup_code()

    assert code is not None
    assert re.fullmatch(r"[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}", code)
    assert auth.setup_code() == code


def test_complete_setup_creates_the_first_admin(auth: AuthService) -> None:
    code = auth.setup_code()
    assert code is not None

    admin = auth.complete_setup(code.lower().replace("-", " "), "Apo", PASSWORD)  # typed casually

    assert admin.username == "apo"
    assert admin.role == Role.ADMIN
    assert not auth.is_setup_required()


def test_complete_setup_refuses_wrong_code(auth: AuthService) -> None:
    problem = raised_problem(lambda: auth.complete_setup("AAAA-BBBB-CCCC", "apo", PASSWORD))

    assert (problem.status, problem.code) == (403, "wrong_setup_code")
    assert auth.is_setup_required()


def test_complete_setup_only_once(auth: AuthService) -> None:
    code = auth.setup_code()
    assert code is not None
    auth.complete_setup(code, "apo", PASSWORD)

    problem = raised_problem(lambda: auth.complete_setup(code, "intruder", PASSWORD))

    assert (problem.status, problem.code) == (409, "setup_done")


# --- Users

def test_usernames_are_lowercase_and_unique(auth: AuthService) -> None:
    user = auth.create_user("  Kid ", PASSWORD, Role.USER)

    problem = raised_problem(lambda: auth.create_user("KID", PASSWORD, Role.USER))

    assert user.username == "kid"
    assert (problem.status, problem.code) == (409, "already_exists")


@pytest.mark.parametrize("username", ["", "with space", "slash/name", "x" * 33, "émile"])
def test_refuses_invalid_username(auth: AuthService, username: str) -> None:
    problem = raised_problem(lambda: auth.create_user(username, PASSWORD, Role.USER))

    assert (problem.status, problem.code) == (422, "validation_error")
    assert problem.extra["errors"][0]["field"] == "username"


def test_refuses_short_password(auth: AuthService) -> None:
    problem = raised_problem(lambda: auth.create_user("kid", "short", Role.USER))

    assert problem.extra["errors"][0]["field"] == "password"


def test_stores_only_an_argon2id_hash_of_the_password(auth: AuthService, database: Database) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)

    with database.session() as session:
        password_hash = session.scalars(select(User.password_hash)).one()

    assert password_hash.startswith("$argon2id$")
    assert PASSWORD not in password_hash


# --- Logins

def test_login_returns_token_that_authenticates(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)

    new_token = auth.create_token("Kid", PASSWORD, "laptop (pictorio 0.1.0)")
    authentication = auth.authenticate(new_token.token)

    assert re.fullmatch(r"pk_[A-Za-z0-9_-]{43}", new_token.token)
    assert new_token.user.username == "kid"
    assert authentication.user == new_token.user
    assert authentication.token_id == new_token.info.id


def test_stores_only_the_tokens_sha256(auth: AuthService, database: Database) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    new_token = auth.create_token("kid", PASSWORD, "laptop")

    with database.session() as session:
        stored = session.scalars(select(ApiToken)).one()

    assert len(stored.token_sha256) == 64
    assert new_token.token not in stored.token_sha256


@pytest.mark.parametrize(("username", "password"), [("kid", "wrong password"), ("nobody", PASSWORD)])
def test_wrong_username_or_password_get_the_same_answer(auth: AuthService, username: str, password: str) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)

    problem = raised_problem(lambda: auth.create_token(username, password, "laptop"))

    assert (problem.status, problem.code) == (401, "not_authenticated")
    assert problem.detail == "Wrong username or password, or the token is unknown or revoked."


def test_unknown_token_is_not_authenticated(auth: AuthService) -> None:
    problem = raised_problem(lambda: auth.authenticate("pk_unknown"))

    assert (problem.status, problem.code) == (401, "not_authenticated")


def test_using_a_token_updates_last_used(auth: AuthService, clock: TestClock) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    new_token = auth.create_token("kid", PASSWORD, "laptop")

    clock.advance(timedelta(hours=2))
    auth.authenticate(new_token.token)

    assert auth.list_tokens(new_token.user.id)[0].last_used_at == clock.now()


def test_lists_only_own_tokens(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    auth.create_user("apo", PASSWORD, Role.ADMIN)
    laptop = auth.create_token("kid", PASSWORD, "laptop")
    auth.create_token("kid", PASSWORD, "phone")
    auth.create_token("apo", PASSWORD, "desktop")

    devices = [token.device_name for token in auth.list_tokens(laptop.user.id)]

    assert devices == ["laptop", "phone"]


def test_revoked_token_no_longer_authenticates(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    new_token = auth.create_token("kid", PASSWORD, "laptop")

    auth.revoke_token(new_token.user.id, new_token.info.id)

    assert raised_problem(lambda: auth.authenticate(new_token.token)).status == 401


def test_cannot_revoke_another_users_token(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    admin = auth.create_user("apo", PASSWORD, Role.ADMIN)
    kids_token = auth.create_token("kid", PASSWORD, "laptop")

    problem = raised_problem(lambda: auth.revoke_token(admin.id, kids_token.info.id))

    assert (problem.status, problem.code) == (404, "not_found")
    auth.authenticate(kids_token.token)  # still valid


# --- Too many failed logins

def fail_logins(auth: AuthService, count: int) -> None:
    for _ in range(count):
        raised_problem(lambda: auth.create_token("kid", "wrong password", "laptop"))


def test_blocks_logins_after_ten_failures(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    fail_logins(auth, 10)

    problem = raised_problem(lambda: auth.create_token("kid", PASSWORD, "laptop"))  # even the right password

    assert (problem.status, problem.code) == (429, "too_many_attempts")
    assert problem.headers == {"Retry-After": "900"}


def test_allows_logins_again_after_fifteen_minutes(auth: AuthService, clock: TestClock) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    fail_logins(auth, 10)

    clock.advance(timedelta(minutes=15))

    auth.create_token("kid", PASSWORD, "laptop")


def test_successful_login_resets_the_failure_count(auth: AuthService) -> None:
    auth.create_user("kid", PASSWORD, Role.USER)
    fail_logins(auth, 9)
    auth.create_token("kid", PASSWORD, "laptop")

    fail_logins(auth, 9)

    auth.create_token("kid", PASSWORD, "laptop")  # 18 failures in all, but never 10 in a row
