# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import math
from collections import defaultdict, deque
from datetime import datetime, timedelta

MAX_FAILED_ATTEMPTS = 10
ATTEMPT_WINDOW = timedelta(minutes=15)


class LoginAttempts:
    """Failed logins per username in the last ATTEMPT_WINDOW. Kept in memory: the server is one process,
    and a restart only resets the count."""

    def __init__(self) -> None:
        self._failures: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def record_failure(self, username: str, now: datetime) -> None:
        self._failures[username].append(now)

    def clear(self, username: str) -> None:
        self._failures.pop(username, None)

    def seconds_until_allowed(self, username: str, now: datetime) -> int | None:
        """None if a login may be tried now; otherwise how long until the oldest failure expires."""
        failures = self._failures.get(username)
        if failures is None:
            return None

        while failures and now - failures[0] >= ATTEMPT_WINDOW:
            failures.popleft()

        if len(failures) < MAX_FAILED_ATTEMPTS:
            return None

        return math.ceil((failures[0] + ATTEMPT_WINDOW - now).total_seconds())
