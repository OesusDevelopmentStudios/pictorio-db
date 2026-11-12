# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Each example of the query language is a test, and so is each kind of error."""

from datetime import date

import pytest

from pictorio_db.services.search import All, AnyOf, DateMatch, Node, Not, TagMatch, parse_query
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}


def tag(namespace: str, name: str) -> TagMatch:
    return TagMatch(namespace, name)


def starting(namespace: str, name: str) -> TagMatch:
    return TagMatch(namespace, name, any_name_starting=True)


def general(*names: str) -> tuple[TagMatch, ...]:
    return tuple(tag("general", name) for name in names)


def query(*terms: Node) -> All:
    return All(terms)


def parsed(text: str) -> All:
    return parse_query(text, NAMESPACES)


# --- The examples of the query language

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("general:tag1,tag2,tag3", query(All(general("tag1", "tag2", "tag3")))),
        ("tag1,tag2,tag3", query(All(general("tag1", "tag2", "tag3")))),
        ("rating:nsfw|sfw", query(AnyOf((tag("rating", "nsfw"), tag("rating", "sfw"))))),
        ("album:album_1,album_2", query(All((tag("album", "album_1"), tag("album", "album_2"))))),
        ("album:album_1|album_2", query(AnyOf((tag("album", "album_1"), tag("album", "album_2"))))),
        (
            "general:(tag_1,tag_2)|(tag_3,tag_4)",
            query(AnyOf((All(general("tag_1", "tag_2")), All(general("tag_3", "tag_4"))))),
        ),
        (
            "general:tag1,tag2,tag3 category:artwork rating:nsfw|sfw album:album_1,album_2",
            query(
                All(general("tag1", "tag2", "tag3")),
                tag("category", "artwork"),
                AnyOf((tag("rating", "nsfw"), tag("rating", "sfw"))),
                All((tag("album", "album_1"), tag("album", "album_2"))),
            ),
        ),
        (
            "(category:photo,rating:sfw)|(category:artwork,author:sample_artist)",
            query(
                AnyOf((
                    All((tag("category", "photo"), tag("rating", "sfw"))),
                    All((tag("category", "artwork"), tag("author", "sample_artist"))),
                ))
            ),
        ),
        ("category:artwork|author:x", query(AnyOf((tag("category", "artwork"), tag("author", "x"))))),
        ("-rating:nsfw|questionable", query(Not(AnyOf((tag("rating", "nsfw"), tag("rating", "questionable")))))),
        (
            "(category:photo,-rating:nsfw)|category:artwork",
            query(AnyOf((All((tag("category", "photo"), Not(tag("rating", "nsfw")))), tag("category", "artwork")))),
        ),
        ("author:pol*,mar*", query(All((starting("author", "pol"), starting("author", "mar"))))),
        (
            "year:2024|2025 album:vacation*",
            query(
                AnyOf((
                    DateMatch(date(2024, 1, 1), date(2024, 12, 31)),
                    DateMatch(date(2025, 1, 1), date(2025, 12, 31)),
                )),
                starting("album", "vacation"),
            ),
        ),
    ],
)
def test_examples(text: str, expected: All) -> None:
    assert parsed(text) == expected


# --- Further rules

def test_empty_query_finds_every_image() -> None:
    assert parsed("   ") == All(())


def test_unknown_prefix_stays_part_of_a_general_tag() -> None:
    assert parsed("re:zero") == query(tag("general", "re:zero"))


def test_prefix_of_a_group_applies_inside_it() -> None:
    assert parsed("album:(a1,a2)") == query(All((tag("album", "a1"), tag("album", "a2"))))


def test_own_prefix_wins_over_the_groups() -> None:
    assert parsed("album:(a1,category:photo)") == query(All((tag("album", "a1"), tag("category", "photo"))))


def test_star_alone_means_any_tag_in_the_namespace() -> None:
    assert parsed("character:*") == query(starting("character", ""))


def test_values_and_prefixes_are_normalised_like_tags() -> None:
    assert parsed("Author:Pol* SUMMER") == query(starting("author", "pol"), tag("general", "summer"))


def test_minus_at_the_start_of_a_term_negates_all_of_it() -> None:
    assert parsed("-a,b") == query(Not(All(general("a", "b"))))


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("month:2024-02", date(2024, 2, 1), date(2024, 2, 29)),  # a leap year
        ("month:2025-12", date(2025, 12, 1), date(2025, 12, 31)),
        ("date:2025-07-14", date(2025, 7, 14), date(2025, 7, 14)),
        ("date:2025-01-01..2025-06-30", date(2025, 1, 1), date(2025, 6, 30)),
        ("year:2020..2022", date(2020, 1, 1), date(2022, 12, 31)),
    ],
)
def test_dates(text: str, first: date, last: date) -> None:
    assert parsed(text) == query(DateMatch(first, last))


# --- Errors: what was expected, and where

@pytest.mark.parametrize(
    ("text", "position", "detail"),
    [
        ("(a,b", 4, "Expected ')'"),
        ("a)", 1, "Unexpected ')'"),
        ("a,,b", 2, "Expected a value"),
        ("|a", 0, "Expected a value"),
        ("a|", 2, "Expected a value"),
        ("-", 1, "Expected a value"),
        ("p*l", 1, "'*' can only be at the end of a value"),
        ("general:(a, b)", 11, "Expected a value; a space ends a term, so a group cannot contain spaces"),
        ("general:(a ,b)", 10, "Expected ')'; a space ends a term, so a group cannot contain spaces"),
        ("year:20x5", 5, "Expected a year like 2025"),
        ("month:2025-7", 6, "Expected a month like 2025-07"),
        ("date:2025-13-01", 5, "No such date: 2025-13-01"),
        ("date:2025-06-30..2025-01-01", 5, "The range ends before it starts"),
        ("date:2025-01-01..later", 17, "Expected a date like 2025-07-14"),
    ],
)
def test_errors_say_what_was_expected_and_where(text: str, position: int, detail: str) -> None:
    with pytest.raises(Problem) as raised:
        parsed(text)

    assert (raised.value.status, raised.value.code) == (400, "invalid_query")
    assert (raised.value.extra["position"], raised.value.detail) == (position, detail)


def test_error_position_counts_from_the_start_of_the_whole_query() -> None:
    with pytest.raises(Problem) as raised:
        parsed("summer beach,,sand")

    assert raised.value.extra["position"] == 13
