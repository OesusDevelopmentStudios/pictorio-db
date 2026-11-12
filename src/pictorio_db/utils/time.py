# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The database stores UTC times without a time zone; the API sends them with one ('Z')."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """The current time in UTC, without a time zone attached, as the database stores it."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_utc(stored_time: datetime) -> datetime:
    """A UTC time from the database, marked as UTC so that it is sent as e.g. 2026-11-12T10:20:03Z."""
    return stored_time.replace(tzinfo=UTC)
