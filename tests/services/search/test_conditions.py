# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Queries run against a small library on a real database."""

from datetime import datetime

import pytest
from sqlalchemy import select

from pictorio_db.db import Database
from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.search import (
    TagMatch,
    apply_hidden_filters,
    matching_condition,
    mentioned_tags,
    parse_query,
    tree_matches,
)
from pictorio_db.services.tags import TagName

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}

# name → (tags, taken_at)
LIBRARY = {
    "beach": (
        ["category:photo", "rating:sfw", "general:summer", "general:on_the_beach", "album:vacation_2024"],
        datetime(2024, 7, 14, 16, 2),
    ),
    "sunset_art": (["category:artwork", "author:sample_artist", "rating:nsfw"], datetime(2025, 1, 10, 9, 0)),
    "duo": (
        ["category:artwork", "author:pol_one", "author:mar_two", "rating:questionable"],
        datetime(2025, 6, 30, 23, 59),
    ),
    "family": (
        ["category:photo", "rating:sfw", "character:hero", "album:vacation_2025"],
        datetime(2025, 7, 1, 0, 0),
    ),
    "untagged": ([], datetime(2023, 3, 3, 3, 3)),
}


@pytest.fixture
def library(database: Database) -> Database:
    with database.session() as session:
        namespace_rows = session.execute(select(Namespace.name, Namespace.id))
        namespace_ids = {name: namespace_id for name, namespace_id in namespace_rows}
        tag_ids: dict[str, int] = {}
        for number, (name, (tags, taken_at)) in enumerate(LIBRARY.items()):
            image = Image(
                sha256=f"{number:064x}",
                storage_path=f"{name}.jpg",
                original_filename=f"{name}.jpg",
                mime_type="image/jpeg",
                width=1,
                height=1,
                file_size=1,
                taken_at=taken_at,
                taken_at_source="exif",
                imported_at=taken_at,
                updated_at=taken_at,
            )
            session.add(image)
            session.flush()
            for tag_text in tags:
                if tag_text not in tag_ids:
                    namespace, tag_name = tag_text.split(":")
                    tag = Tag(namespace_id=namespace_ids[namespace], name=tag_name)
                    session.add(tag)
                    session.flush()
                    tag_ids[tag_text] = tag.id

                session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag_ids[tag_text]))

        session.commit()

    return database


def found(database: Database, query: str, hidden_filters: list[str] | None = None) -> set[str]:
    tree = parse_query(query, NAMESPACES)
    if hidden_filters:
        tree = apply_hidden_filters(query, tree, hidden_filters, NAMESPACES).tree

    with database.session() as session:
        file_names = session.scalars(select(Image.original_filename).where(matching_condition(tree)))
        return {file_name.removesuffix(".jpg") for file_name in file_names}


# --- Searching

@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", {"beach", "sunset_art", "duo", "family", "untagged"}),
        ("category:artwork", {"sunset_art", "duo"}),
        ("summer,on_the_beach", {"beach"}),
        ("summer,hero", set()),
        ("rating:nsfw|questionable", {"sunset_art", "duo"}),
        ("-rating:nsfw|questionable", {"beach", "family", "untagged"}),  # untagged images are not excluded
        ("category:photo -album:vacation_2024", {"family"}),
        ("album:vacation*", {"beach", "family"}),
        ("author:pol*,mar*", {"duo"}),
        ("character:*", {"family"}),
        ("(category:photo,rating:sfw)|(category:artwork,author:sample_artist)", {"beach", "family", "sunset_art"}),
        ("(category:photo,-rating:sfw)|category:artwork", {"sunset_art", "duo"}),
        ("year:2025", {"sunset_art", "duo", "family"}),
        ("year:2024|2023", {"beach", "untagged"}),
        ("month:2025-07", {"family"}),
        ("date:2025-01-01..2025-06-30", {"sunset_art", "duo"}),  # the last day counts until midnight
        ("nonexistent", set()),
    ],
)
def test_finds_the_matching_images(library: Database, query: str, expected: set[str]) -> None:
    assert found(library, query) == expected


# --- Hidden-by-default filters

def effective_query(query: str, hidden_filters: list[str]) -> str:
    return apply_hidden_filters(query, parse_query(query, NAMESPACES), hidden_filters, NAMESPACES).effective_query


def test_hidden_filter_hides_images_from_the_default_view(library: Database) -> None:
    assert found(library, "", ["rating:nsfw"]) == {"beach", "duo", "family", "untagged"}
    assert effective_query("", ["rating:nsfw"]) == "-rating:nsfw"


def test_searching_for_a_hidden_tag_shows_it(library: Database) -> None:
    assert found(library, "rating:nsfw", ["rating:nsfw"]) == {"sunset_art"}
    assert effective_query("rating:nsfw", ["rating:nsfw"]) == "rating:nsfw"


def test_mentioning_the_tag_negatively_also_skips_the_filter() -> None:
    assert effective_query("-rating:nsfw", ["rating:nsfw"]) == "-rating:nsfw"


def test_filter_and_query_overlap_through_wildcards() -> None:
    assert effective_query("character:hero", ["character:*"]) == "character:hero"
    assert effective_query("character:*", ["character:hero"]) == "character:*"


def test_filter_with_several_tags_is_added_as_one_term(library: Database) -> None:
    hidden_filters = ["rating:nsfw|questionable"]

    assert found(library, "category:artwork", hidden_filters) == set()
    assert effective_query("category:artwork", hidden_filters) == "category:artwork -rating:nsfw|questionable"


def test_each_filter_is_checked_on_its_own() -> None:
    assert effective_query("rating:nsfw", ["rating:nsfw", "category:refs"]) == "rating:nsfw -category:refs"


def test_lists_the_tags_a_query_mentions() -> None:
    tree = parse_query("-rating:nsfw|(album:a*,year:2025)", NAMESPACES)

    assert mentioned_tags(tree) == [
        TagMatch("rating", "nsfw"),
        TagMatch("album", "a", any_name_starting=True),
    ]


# --- The same meaning without the database

@pytest.mark.parametrize(
    "query",
    ["category:artwork", "-rating:nsfw|questionable", "author:pol*,mar*", "character:*", "year:2025", "summer,hero"],
)
def test_tree_matches_agrees_with_the_database(library: Database, query: str) -> None:
    tree = parse_query(query, NAMESPACES)
    in_memory = {
        name
        for name, (tag_texts, taken_at) in LIBRARY.items()
        if tree_matches(tree, [TagName(*text.split(":")) for text in tag_texts], taken_at)
    }

    assert in_memory == found(library, query)
