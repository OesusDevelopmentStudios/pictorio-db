# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2id with the library's defaults, which follow RFC 9106's recommendation.
_hasher = PasswordHasher()

# Checked when the username does not exist, so that a wrong username takes as long as a wrong password
# and the response time does not reveal which usernames exist.
_UNKNOWN_USER_HASH = _hasher.hash("password of a user that does not exist")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """password_hash is None for a user that does not exist; the check then takes just as long."""
    try:
        _hasher.verify(password_hash or _UNKNOWN_USER_HASH, password)
    except (VerificationError, InvalidHashError):
        return False

    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with older parameters than the current ones."""
    return _hasher.check_needs_rehash(password_hash)
