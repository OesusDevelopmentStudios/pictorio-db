# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from collections.abc import Callable, Collection
from datetime import datetime

from sqlalchemy import ColumnElement, and_, delete, not_, select, true

from pictorio_db.db import Database
from pictorio_db.db.models import User, UserRestriction
from pictorio_db.services.auth import Role, UserInfo
from pictorio_db.services.search import (
    All,
    checked_terms,
    matching_condition,
    mentioned_tags,
    parse_query,
    tree_matches,
)
from pictorio_db.services.tags import TagName
from pictorio_db.utils.problems import Problem


class Restrictions:
    """One user's restrictions, parsed once per request. The only place that decides whether a user may see
    an image or use a tag. Admins have none."""

    def __init__(self, terms: list[All]) -> None:
        self._terms = terms

    @property
    def active(self) -> bool:
        return bool(self._terms)

    def visible_images_filter(self) -> ColumnElement[bool]:
        """Added to every query that reads images: search, lookup by id, file, thumbnail, bulk changes."""
        return and_(true(), *(not_(matching_condition(term)) for term in self._terms))

    def is_visible(self, tags: Collection[TagName], taken_at: datetime | None) -> bool:
        return not any(tree_matches(term, tags, taken_at) for term in self._terms)

    def check_tags_allowed(self, tags_after: Collection[TagName], taken_at: datetime | None) -> None:
        """For uploads and tag changes: an image with these tags must stay visible to the user. Raises
        403 tag_restricted naming the image's tags that the applying restrictions mention."""
        applying = [term for term in self._terms if tree_matches(term, tags_after, taken_at)]
        if not applying:
            return

        offending = {
            str(tag)
            for term in applying
            for tag in tags_after
            if any(tree_matches(match, [tag], None) for match in mentioned_tags(term))
        }
        raise Problem(
            403,
            "tag_restricted",
            "Tag not allowed",
            "An admin has restricted these tags for your account.",
            tags=sorted(offending),
        )

    def is_tag_hidden(self, tag: TagName) -> bool:
        """For autocomplete: hidden if an image with only this tag would be restricted."""
        return not self.is_visible([tag], None)


class AccessService:
    """Per-user restricted tags, set by an admin: a block list of search terms."""

    def __init__(self, database: Database, namespace_names: Callable[[], Collection[str]]) -> None:
        self._database = database
        self._namespace_names = namespace_names

    def restricted_terms(self, user_id: int) -> list[str]:
        with self._database.session() as session:
            terms = select(UserRestriction.term).where(UserRestriction.user_id == user_id)
            return list(session.scalars(terms.order_by(UserRestriction.term)))

    def checked_terms(self, terms: list[str]) -> list[str]:
        """Trimmed, sorted, without repeats. Raises 422 validation_error; call it before changing anything."""
        return sorted(set(checked_terms(terms, "body.restricted_tags", self._namespace_names())))

    def set_restricted_terms(self, user_id: int, terms: list[str]) -> list[str]:
        """Replaces the whole list. Terms may name tags that do not exist yet. Raises 422 validation_error."""
        cleaned = self.checked_terms(terms)
        with self._database.session() as session:
            session.execute(delete(UserRestriction).where(UserRestriction.user_id == user_id))
            session.add_all(UserRestriction(user_id=user_id, term=term) for term in cleaned)
            session.commit()

        return cleaned

    def restricted_users(self) -> dict[str, Restrictions]:
        """Every user whose restrictions are in effect, by username."""
        query = (
            select(User.username, UserRestriction.term)
            .join(User, User.id == UserRestriction.user_id)
            .where(User.role == Role.USER)
        )
        terms_by_user: dict[str, list[str]] = {}
        with self._database.session() as session:
            for username, term in session.execute(query):
                terms_by_user.setdefault(username, []).append(term)

        namespace_names = self._namespace_names()
        return {
            username: Restrictions([parse_query(term, namespace_names) for term in terms])
            for username, terms in terms_by_user.items()
        }

    def restrictions_for(self, user: UserInfo) -> Restrictions:
        """Read at each request, so a change applies at once. Admins are never restricted."""
        if user.role == Role.ADMIN:
            return Restrictions([])

        namespace_names = self._namespace_names()
        return Restrictions([parse_query(term, namespace_names) for term in self.restricted_terms(user.id)])
