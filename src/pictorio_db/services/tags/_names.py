# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The rules for tag and namespace names."""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass

from pictorio_db.db.models import NAMESPACE_NAME_MAX_LENGTH, TAG_NAME_MAX_LENGTH
from pictorio_db.utils.problems import Problem

GENERAL_NAMESPACE = "general"  # the namespace of a tag written without one: "summer" is "general:summer"

# Search fields that use the namespace syntax (year:2025), so no namespace may have these names.
RESERVED_NAMESPACE_NAMES = frozenset({"year", "month", "date"})

# Tag names can become folder names: no path separators.
_PATH_CHARACTERS = {"/": "'/'", "\\": "'\\'"}
# Operators of the search language
_SEARCH_OPERATORS = {",": "','", "|": "'|'", "(": "'('", ")": "')'", "*": "'*'"}

_NAMESPACE_NAME_PATTERN = re.compile(rf"[a-z0-9_]{{1,{NAMESPACE_NAME_MAX_LENGTH}}}")


@dataclass(frozen=True)
class TagName:
    namespace: str
    name: str

    def __str__(self) -> str:
        return f"{self.namespace}:{self.name}"


def split_tag(text: str, namespace_names: Collection[str]) -> tuple[str, str]:
    """Splits at the first ':' only if the part before it is an existing namespace (any case);
    otherwise the whole text is a general tag, so "re:zero" stays one tag."""
    prefix, separator, rest = text.partition(":")
    namespace = prefix.strip().lower()
    if separator and namespace in namespace_names:
        return namespace, rest

    return GENERAL_NAMESPACE, text


def normalized_name_prefix(typed_text: str) -> str:
    """What the user has typed so far, in the form of a tag name: "On the Be" → "on_the_be". Not checked
    against the rules: it is only compared with existing tags."""
    return re.sub(" +", "_", unicodedata.normalize("NFC", typed_text).lstrip().lower())


def normalized_tag_name(name: str) -> str:
    """Trims, lowercases and joins words with '_', then checks the result. Raises 422 invalid_tag."""
    normalized = re.sub(" +", "_", unicodedata.normalize("NFC", name).strip().lower())
    problem = _tag_name_problem(normalized)
    if problem is not None:
        raise Problem(422, "invalid_tag", "Invalid tag", problem, tag=name)

    return normalized


def normalized_namespace_name(name: str) -> str:
    normalized = name.strip().lower()
    if not _NAMESPACE_NAME_PATTERN.fullmatch(normalized):
        raise _invalid_namespace_name(
            f"1 to {NAMESPACE_NAME_MAX_LENGTH} characters: letters a-z, digits and '_'"
        )

    if normalized in RESERVED_NAMESPACE_NAMES:
        raise _invalid_namespace_name(f"'{normalized}' is a search field: year, month and date are reserved")

    return normalized


def _tag_name_problem(name: str) -> str | None:
    if not name:
        return "A tag name cannot be empty."

    if name in (".", ".."):
        return "A tag name cannot be '.' or '..'."

    for character in name:
        if character in _PATH_CHARACTERS:
            return f"A tag name cannot contain {_PATH_CHARACTERS[character]}."

        if character in _SEARCH_OPERATORS:
            return f"A tag name cannot contain {_SEARCH_OPERATORS[character]}: it is a search operator."

        if unicodedata.category(character) == "Cc":  # includes NUL, tab and newline
            return "A tag name cannot contain control characters."

    if name.startswith("-"):
        return "A tag name cannot start with '-': it means NOT in a search."

    if len(name) > TAG_NAME_MAX_LENGTH:
        return f"A tag name can have at most {TAG_NAME_MAX_LENGTH} characters."

    return None


def _invalid_namespace_name(message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": "name", "message": message}],
    )
