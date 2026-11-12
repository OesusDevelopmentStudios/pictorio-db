# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from datetime import datetime

import pytest
from sqlalchemy import select

from pictorio_db.db import Database
from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.tags import TagsService

# tag → number of images that carry it
TAGGED_IMAGES = {
    "author:sample_artist": 3,
    "general:samurai": 2,
    "author:sam_winchester": 1,
    "general:on_the_beach": 1,
    "general:a_b": 1,
    "general:axb": 1,
    "character:nobody_yet": 0,
}


def add_tagged_images(database: Database, image_counts: dict[str, int]) -> None:
    with database.session() as session:
        namespace_rows = session.execute(select(Namespace.name, Namespace.id))
        namespace_ids = {name: namespace_id for name, namespace_id in namespace_rows}
        for image_number, (tag_text, image_count) in enumerate(image_counts.items()):
            namespace_name, name = tag_text.split(":")
            tag = Tag(namespace_id=namespace_ids[namespace_name], name=name)
            session.add(tag)
            session.flush()
            for copy_number in range(image_count):
                image = new_image(f"{image_number:02}{copy_number:02}")
                session.add(image)
                session.flush()
                session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag.id))

        session.commit()


def new_image(unique_part: str) -> Image:
    now = datetime(2026, 11, 12, 12, 0)
    return Image(
        sha256=unique_part.ljust(64, "0"),
        storage_path=f"photo/{unique_part}.jpg",
        original_filename=f"{unique_part}.jpg",
        mime_type="image/jpeg",
        width=1,
        height=1,
        file_size=1,
        taken_at=now,
        taken_at_source="import_time",
        imported_at=now,
        updated_at=now,
    )


@pytest.fixture
def tags(database: Database) -> TagsService:
    add_tagged_images(database, TAGGED_IMAGES)
    return TagsService(database, lambda: frozenset({"category", "author"}))


def suggestions(tags: TagsService, prefix: str = "", namespace: str | None = None, limit: int = 20) -> list[str]:
    return [str(match.tag) for match in tags.autocomplete(prefix, namespace, limit)]


def test_most_used_tags_come_first(tags: TagsService) -> None:
    matches = tags.autocomplete()

    assert [(str(match.tag), match.image_count) for match in matches][:2] == [
        ("author:sample_artist", 3),
        ("general:samurai", 2),
    ]


def test_tags_without_images_come_last(tags: TagsService) -> None:
    last = tags.autocomplete()[-1]

    assert (str(last.tag), last.image_count) == ("character:nobody_yet", 0)


def test_equally_used_tags_are_in_alphabetical_order(tags: TagsService) -> None:
    assert suggestions(tags, "general:")[1:] == ["general:a_b", "general:axb", "general:on_the_beach"]


def test_prefix_with_namespace_searches_that_namespace(tags: TagsService) -> None:
    assert suggestions(tags, "author:sam") == ["author:sample_artist", "author:sam_winchester"]


def test_prefix_without_namespace_searches_all_namespaces(tags: TagsService) -> None:
    assert suggestions(tags, "sam") == ["author:sample_artist", "general:samurai", "author:sam_winchester"]


def test_typed_text_is_normalised_like_a_tag(tags: TagsService) -> None:
    assert suggestions(tags, "  On The Be") == ["general:on_the_beach"]


def test_underscore_is_not_a_wildcard(tags: TagsService) -> None:
    assert suggestions(tags, "a_") == ["general:a_b"]


def test_namespace_filter(tags: TagsService) -> None:
    assert suggestions(tags, namespace="Author") == ["author:sample_artist", "author:sam_winchester"]


def test_contradicting_namespaces_find_nothing(tags: TagsService) -> None:
    assert suggestions(tags, "author:pol", namespace="general") == []


def test_unknown_namespace_finds_nothing(tags: TagsService) -> None:
    assert suggestions(tags, namespace="weather") == []


def test_limit(tags: TagsService) -> None:
    assert suggestions(tags, limit=1) == ["author:sample_artist"]
