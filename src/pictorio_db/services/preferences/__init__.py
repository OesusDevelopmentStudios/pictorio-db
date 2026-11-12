# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Each user's preferences: the search filters hidden from their default view."""

from collections.abc import Callable, Collection

from sqlalchemy import select

from pictorio_db.db import Database
from pictorio_db.db.models import UserPreferences
from pictorio_db.services.search import MAX_TERMS, TERM_MAX_LENGTH, checked_terms

MAX_HIDDEN_FILTERS = MAX_TERMS
HIDDEN_FILTER_MAX_LENGTH = TERM_MAX_LENGTH


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
        """Replaces the whole list. Each filter is one search term without a leading '-' (the '-' is added when
        searching). Raises 422 validation_error naming the filter."""
        cleaned = checked_terms(hidden_filters, "body.hidden_filters", self._namespace_names())
        with self._database.session() as session:
            session.merge(UserPreferences(user_id=user_id, hidden_filters=cleaned))
            session.commit()

        return cleaned

    def rewrite_hidden_filters(self, rewrite: Callable[[str], str | None]) -> None:
        """After a tag rename or delete: every user's filters go through `rewrite`; None removes a filter."""
        with self._database.session() as session:
            for preferences in session.scalars(select(UserPreferences)):
                rewritten = (new_filter for new_filter in map(rewrite, preferences.hidden_filters) if new_filter)
                new_filters = list(dict.fromkeys(rewritten))
                if new_filters != preferences.hidden_filters:
                    preferences.hidden_filters = new_filters

            session.commit()


__all__ = ["HIDDEN_FILTER_MAX_LENGTH", "MAX_HIDDEN_FILTERS", "PreferencesService"]
