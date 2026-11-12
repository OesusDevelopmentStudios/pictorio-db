# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest

from pictorio_db.services.search import parse_query, renamed_in_term, term_text, without_tag_in_term
from pictorio_db.services.tags import TagName

NAMESPACES = {"general", "category", "author", "rating", "character"}
NSFW = TagName("rating", "nsfw")


@pytest.mark.parametrize(
    "term",
    [
        "rating:nsfw",
        "rating:nsfw|questionable",
        "category:photo,rating:nsfw",
        "category:(photo|artwork),-rating:nsfw",
        "(category:photo,author:anon)|category:artwork",
        "general:beach|-(rating:nsfw|questionable)",
        "(category:photo|category:artwork)|general:beach",
        "character:*",
        "author:an*",
        "year:2024",
        "date:2024-05-01..2024-06-30,general:beach",  # a prefix applies to the values after it
    ],
)
def test_text_parses_back_to_the_same_term(term: str) -> None:
    [tree] = parse_query(term, NAMESPACES).operands

    assert parse_query(term_text(tree), NAMESPACES).operands == (tree,)


@pytest.mark.parametrize(
    "term, renamed",
    [
        ("rating:nsfw", "rating:explicit"),
        ("rating:nsfw|questionable", "rating:explicit|rating:questionable"),
        ("rating:explicit|nsfw", "rating:explicit"),  # the two became one
        ("category:photo,-rating:nsfw", "category:photo,-rating:explicit"),
        ("rating:sfw|questionable", "rating:sfw|questionable"),  # not named: kept as written
        ("rating:ns*", "rating:ns*"),  # a pattern, not the tag
    ],
)
def test_rename_replaces_the_tag(term: str, renamed: str) -> None:
    assert renamed_in_term(term, NSFW, TagName("rating", "explicit"), NAMESPACES) == renamed


def test_rename_can_change_the_namespace() -> None:
    assert renamed_in_term("general:nude|rating:nsfw", TagName("general", "nude"), NSFW, NAMESPACES) == "rating:nsfw"


@pytest.mark.parametrize(
    "term, remaining",
    [
        ("rating:nsfw", None),
        ("rating:nsfw|questionable", "rating:questionable"),
        ("rating:(nsfw|questionable),category:photo", "rating:questionable,category:photo"),
        ("category:photo,rating:nsfw", None),
        ("category:photo,-rating:nsfw", None),
        ("general:beach|-rating:nsfw", "general:beach"),
        ("rating:nsfw|-general:beach", "(-general:beach)"),  # no leading '-': stored terms refuse it
        ("character:*", "character:*"),
        ("rating:sfw", "rating:sfw"),
    ],
)
def test_delete_drops_the_tag_from_an_or_and_otherwise_the_term(term: str, remaining: str | None) -> None:
    assert without_tag_in_term(term, NSFW, NAMESPACES) == remaining
