# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Each user's preferences: the search filters hidden from their default view."""

from collections.abc import Callable, Collection

from pictorio_db.db import Database
from pictorio_db.db.models import UserPreferences
from pictorio_db.services.search import parse_query
from pictorio_db.utils.problems import Problem

MAX_HIDDEN_FILTERS = 50
HIDDEN_FILTER_MAX_LENGTH = 200


class PreferencesService:
    def __init__(self, database: Database, namespace_names: Callable[[], Collection[str]]) -> None:
        self._database = database
        self._namespace_names = namespace_names

    def hidden_filters(self, user_id: int) -> list[str]:
        """[] for a user who has not set any."""
        with self._database.session() as session:
            preferences = session.get(UserPreferences, user_id)
            return [] if preferences is None else list(preferences.hidden_filters)

    def set_hidden_filters(self, user_id: int, hidden_filters: list[str]) -> list[str]:
        """Replaces the whole list. Each filter must be one search term without a leading '-' (the '-' is added
        when searching). Raises 422 validation_error naming the filter."""
        cleaned = [hidden_filter.strip() for hidden_filter in hidden_filters]
        if len(cleaned) > MAX_HIDDEN_FILTERS:
            raise _invalid("body.hidden_filters", f"At most {MAX_HIDDEN_FILTERS} filters.")

        for index, hidden_filter in enumerate(cleaned):
            self._check_filter(index, hidden_filter)

        with self._database.session() as session:
            session.merge(UserPreferences(user_id=user_id, hidden_filters=cleaned))
            session.commit()

        return cleaned

    def _check_filter(self, index: int, hidden_filter: str) -> None:
        field = f"body.hidden_filters.{index}"
        has_space = any(character.isspace() for character in hidden_filter)
        if not hidden_filter or len(hidden_filter) > HIDDEN_FILTER_MAX_LENGTH or has_space:
            raise _invalid(field, f"One search term: no spaces, 1 to {HIDDEN_FILTER_MAX_LENGTH} characters.")

        if hidden_filter.startswith("-"):
            raise _invalid(field, "Write the term without '-': it is added when searching.")

        try:
            parse_query(hidden_filter, self._namespace_names())
        except Problem as problem:
            position = problem.extra.get("position")
            raise _invalid(field, f"{problem.detail} (at position {position})") from None


def _invalid(field: str, message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": field, "message": message}],
    )


__all__ = ["HIDDEN_FILTER_MAX_LENGTH", "MAX_HIDDEN_FILTERS", "PreferencesService"]
