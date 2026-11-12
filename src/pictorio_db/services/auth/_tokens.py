# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import hashlib
import secrets

TOKEN_PREFIX = "pk_"  # makes the tokens easy to recognise, e.g. by secret scanners
TOKEN_RANDOM_BYTES = 32


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
