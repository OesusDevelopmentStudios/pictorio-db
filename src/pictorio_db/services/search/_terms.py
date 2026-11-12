# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Single search terms as stored lists: hidden filters and restrictions. And whether a term matches an image
whose tags are known, without asking the database."""

from collections.abc import Collection
from datetime import datetime

from pictorio_db.services.search._parser import All, AnyOf, DateMatch, Node, Not, TagMatch, parse_query
from pictorio_db.services.tags import TagName
from pictorio_db.utils.problems import Problem

MAX_TERMS = 50
TERM_MAX_LENGTH = 200


def checked_terms(terms: list[str], field: str, namespace_names: Collection[str]) -> list[str]:
    """Trims the terms and checks each: one search term, no spaces, no leading '-', valid syntax. Raises 422
    validation_error naming the term, e.g. body.hidden_filters.1."""
    cleaned = [term.strip() for term in terms]
    if len(cleaned) > MAX_TERMS:
        raise _invalid(field, f"At most {MAX_TERMS} terms.")

    for index, term in enumerate(cleaned):
        _check_term(term, f"{field}.{index}", namespace_names)

    return cleaned


def tree_matches(node: Node, tags: Collection[TagName], taken_at: datetime | None) -> bool:
    """The same meaning as the database condition built from the tree, for an image not stored yet."""
    if isinstance(node, TagMatch):
        return any(_tag_matches(node, tag) for tag in tags)

    if isinstance(node, DateMatch):
        return taken_at is not None and node.first <= taken_at.date() <= node.last

    if isinstance(node, Not):
        return not tree_matches(node.operand, tags, taken_at)

    if isinstance(node, All):
        return all(tree_matches(operand, tags, taken_at) for operand in node.operands)

    assert isinstance(node, AnyOf)
    return any(tree_matches(operand, tags, taken_at) for operand in node.operands)


def _tag_matches(match: TagMatch, tag: TagName) -> bool:
    if tag.namespace != match.namespace:
        return False

    return tag.name.startswith(match.name) if match.any_name_starting else tag.name == match.name


def _check_term(term: str, field: str, namespace_names: Collection[str]) -> None:
    has_space = any(character.isspace() for character in term)
    if not term or len(term) > TERM_MAX_LENGTH or has_space:
        raise _invalid(field, f"One search term: no spaces, 1 to {TERM_MAX_LENGTH} characters.")

    if term.startswith("-"):
        raise _invalid(field, "Write the term without a leading '-'.")

    try:
        parse_query(term, namespace_names)
    except Problem as problem:
        raise _invalid(field, f"{problem.detail} (at position {problem.extra.get('position')})") from None


def _invalid(field: str, message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": field, "message": message}],
    )
