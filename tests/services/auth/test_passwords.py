# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pictorio_db.services.auth._passwords import hash_password, verify_password


def test_verifies_the_right_password_only() -> None:
    password_hash = hash_password("correct horse battery")

    assert verify_password(password_hash, "correct horse battery")
    assert not verify_password(password_hash, "Correct horse battery")


def test_unknown_user_never_matches() -> None:
    # Even the password of the dummy hash, which is checked for unknown users to keep the timing equal
    assert not verify_password(None, "password of a user that does not exist")


def test_damaged_hash_does_not_match() -> None:
    assert not verify_password("not an argon2 hash", "correct horse battery")
