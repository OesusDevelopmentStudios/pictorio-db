# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""One test per rule for tag and namespace names."""

import pytest

from pictorio_db.services.tags import (
    GENERAL_NAMESPACE,
    TagName,
    normalized_namespace_name,
    normalized_tag_name,
    split_tag,
)
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}


def invalid_tag_problem(name: str) -> Problem:
    with pytest.raises(Problem) as raised:
        normalized_tag_name(name)

    assert (raised.value.status, raised.value.code) == (422, "invalid_tag")
    assert raised.value.extra["tag"] == name  # the client learns which tag was wrong
    return raised.value


# --- Normalising tag names

def test_trims_leading_and_trailing_whitespace() -> None:
    assert normalized_tag_name("  summer \t") == "summer"


def test_converts_to_lowercase() -> None:
    assert normalized_tag_name("Summer") == "summer"


@pytest.mark.parametrize("name", ["ąę", "日本", "café"])
def test_allows_unicode(name: str) -> None:
    assert normalized_tag_name(name) == name


def test_treats_both_unicode_forms_of_a_letter_as_the_same() -> None:
    composed = "café"  # é as one character
    decomposed = "café"  # e followed by a combining accent

    assert normalized_tag_name(decomposed) == normalized_tag_name(composed)


def test_joins_words_with_one_underscore() -> None:
    assert normalized_tag_name("on   the beach") == "on_the_beach"


# --- Rejected tag names

@pytest.mark.parametrize("name", ["a/b", "a\\b"])
def test_rejects_path_separators(name: str) -> None:
    assert "cannot contain" in invalid_tag_problem(name).detail


@pytest.mark.parametrize("name", ["a\x00b", "a\tb", "a\nb", "a\x7fb"])
def test_rejects_control_characters(name: str) -> None:
    assert invalid_tag_problem(name).detail == "A tag name cannot contain control characters."


@pytest.mark.parametrize("name", [".", "..", " .. "])
def test_rejects_dot_names(name: str) -> None:
    assert invalid_tag_problem(name).detail == "A tag name cannot be '.' or '..'."


@pytest.mark.parametrize("name", ["a,b", "a|b", "(a", "a)", "pol*"])
def test_rejects_search_operators(name: str) -> None:
    assert "search operator" in invalid_tag_problem(name).detail


def test_rejects_leading_minus() -> None:
    assert "cannot start with '-'" in invalid_tag_problem("-summer").detail


def test_allows_minus_inside_a_name() -> None:
    assert normalized_tag_name("sci-fi") == "sci-fi"


@pytest.mark.parametrize("name", ["", "   "])
def test_rejects_empty_names(name: str) -> None:
    assert invalid_tag_problem(name).detail == "A tag name cannot be empty."


def test_allows_one_hundred_characters_but_not_more() -> None:
    assert normalized_tag_name("x" * 100) == "x" * 100
    assert "at most 100 characters" in invalid_tag_problem("x" * 101).detail


# --- Splitting "namespace:name"

def test_splits_at_an_existing_namespace() -> None:
    assert split_tag("author:polina_graff", NAMESPACES) == ("author", "polina_graff")


def test_text_without_namespace_is_general() -> None:
    assert split_tag("summer", NAMESPACES) == (GENERAL_NAMESPACE, "summer")


def test_unknown_namespace_stays_part_of_a_general_tag() -> None:
    assert split_tag("re:zero", NAMESPACES) == (GENERAL_NAMESPACE, "re:zero")


def test_splits_only_at_the_first_colon() -> None:
    assert split_tag("album:trip:paris", NAMESPACES) == ("album", "trip:paris")


def test_namespace_prefix_is_case_insensitive() -> None:
    assert split_tag("Author:Pol", NAMESPACES) == ("author", "Pol")


def test_tag_is_written_with_its_namespace() -> None:
    assert str(TagName("general", "summer")) == "general:summer"


# --- Namespace names

def test_namespace_name_is_lowercased() -> None:
    assert normalized_namespace_name(" Weather ") == "weather"


@pytest.mark.parametrize("name", ["", "with space", "dash-ed", "ünicode", "x" * 33])
def test_rejects_invalid_namespace_names(name: str) -> None:
    with pytest.raises(Problem) as raised:
        normalized_namespace_name(name)

    assert raised.value.code == "validation_error"
    assert raised.value.extra["errors"][0]["field"] == "name"


@pytest.mark.parametrize("name", ["year", "month", "date"])
def test_rejects_search_field_names_as_namespaces(name: str) -> None:
    with pytest.raises(Problem) as raised:
        normalized_namespace_name(name)

    assert "reserved" in raised.value.extra["errors"][0]["message"]
