# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import re

from pictorio_db.db.models import USERNAME_MAX_LENGTH
from pictorio_db.utils.problems import Problem

PASSWORD_MIN_LENGTH = 8  # NIST SP 800-63B minimum
PASSWORD_MAX_LENGTH = 1024  # long passphrases are fine; only absurd inputs are refused

_USERNAME_PATTERN = re.compile(rf"[a-z0-9._-]{{1,{USERNAME_MAX_LENGTH}}}")


def normalized_username(username: str) -> str:
    """Usernames are compared in lowercase, so 'Apo' and 'apo' are the same account."""
    return username.strip().lower()


def check_username(username: str) -> None:
    if not _USERNAME_PATTERN.fullmatch(username):
        raise _invalid_field(
            "username",
            f"1 to {USERNAME_MAX_LENGTH} characters: letters a-z, digits, '.', '_' and '-'",
        )


def check_password(password: str) -> None:
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise _invalid_field("password", f"{PASSWORD_MIN_LENGTH} to {PASSWORD_MAX_LENGTH} characters")


def _invalid_field(field: str, message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": field, "message": message}],
    )
