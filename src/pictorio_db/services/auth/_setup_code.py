# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import hmac
import secrets

# No 0/O, 1/I/L: the code is read from a log and typed in by hand.
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_GROUP_COUNT = 3
_GROUP_LENGTH = 4  # 12 characters in all, about 60 bits: too many to try over the network


def generate_setup_code() -> str:
    groups = ("".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LENGTH)) for _ in range(_GROUP_COUNT))
    return "-".join(groups)


def setup_codes_match(expected_code: str, entered_code: str) -> bool:
    """Ignores case, dashes and spaces. Compares in constant time."""
    return hmac.compare_digest(_normalized(expected_code), _normalized(entered_code))


def _normalized(code: str) -> bytes:
    return code.upper().replace("-", "").replace(" ", "").encode()
