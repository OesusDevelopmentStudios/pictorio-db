# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, true

from pictorio_db.db import Database
from pictorio_db.db._connection import shuffled_position
from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.search import Order, SearchPage, SearchRequest, SearchService, Sort
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}
FIRST_DAY = datetime(2025, 1, 1, 12, 0)


def add_image(database: Database, number: int, taken_at: datetime, tags: list[str] = ()) -> int:
    """imported_at runs the other way round than taken_at, so the two sorts differ."""
    with database.session() as session:
        image = Image(
            sha256=f"{number:064x}",
            storage_path=f"{number}.jpg",
            original_filename=f"{number}.jpg",
            mime_type="image/jpeg",
            width=1,
            height=1,
            file_size=1,
            taken_at=taken_at,
            taken_at_source="exif",
            imported_at=datetime(2026, 1, 1) - timedelta(days=number),
            updated_at=datetime(2026, 1, 1),
        )
        session.add(image)
        session.flush()
        for tag_text in tags:
            namespace, name = tag_text.split(":")
            namespace_id = session.scalars(select(Namespace.id).where(Namespace.name == namespace)).one()
            tag = session.scalars(select(Tag).where(Tag.namespace_id == namespace_id, Tag.name == name)).first()
            if tag is None:
                tag = Tag(namespace_id=namespace_id, name=name)
                session.add(tag)
                session.flush()

            session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag.id))

        session.commit()
        return image.id


class UnrestrictedSearch:
    """The search service for a user without restrictions."""

    def __init__(self, service: SearchService) -> None:
        self._service = service

    def search(self, request: SearchRequest) -> SearchPage:
        return self._service.search(request, true())


@pytest.fixture
def search(database: Database) -> UnrestrictedSearch:
    return UnrestrictedSearch(SearchService(database, lambda: NAMESPACES))


@pytest.fixture
def image_ids(database: Database) -> list[int]:
    """Seven images, one a day; images 3 and 4 were taken at the same moment. Even numbers are artworks."""
    taken = [FIRST_DAY + timedelta(days=number) for number in range(7)]
    taken[4] = taken[3]
    return [
        add_image(database, number, taken[number], ["category:artwork" if number % 2 == 0 else "category:photo"])
        for number in range(7)
    ]


def all_pages(search: UnrestrictedSearch, request: SearchRequest) -> list[int]:
    found: list[int] = []
    cursor = None
    while True:
        page = search.search(SearchRequest(**{**vars(request), "cursor": cursor}))
        found += page.image_ids
        cursor = page.next_cursor
        if cursor is None:
            return found


def invalid_field(action: object) -> str:
    with pytest.raises(Problem) as raised:
        action()  # type: ignore[operator]

    assert raised.value.code == "validation_error"
    return raised.value.extra["errors"][0]["field"]


# --- Sorting

def test_newest_taken_first_by_default(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    # 3 and 4 were taken at the same moment; the higher id comes first among equals
    assert search.search(SearchRequest()).image_ids == [image_ids[number] for number in (6, 5, 4, 3, 2, 1, 0)]


def test_oldest_first(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    page = search.search(SearchRequest(order=Order.ASC))

    assert page.image_ids == [image_ids[number] for number in (0, 1, 2, 3, 4, 5, 6)]


def test_by_import_time(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    page = search.search(SearchRequest(sort=Sort.IMPORTED_AT))

    assert page.image_ids == image_ids  # image 0 was imported last


# --- Paging

@pytest.mark.parametrize(
    "request_without_cursor",
    [
        SearchRequest(limit=3),
        SearchRequest(limit=3, order=Order.ASC),
        SearchRequest(limit=3, sort=Sort.IMPORTED_AT),
        SearchRequest(limit=2, sort=Sort.RANDOM, seed=42),
    ],
    ids=["taken, newest first", "taken, oldest first", "imported", "random"],
)
def test_pages_together_hold_every_image_once(
    search: UnrestrictedSearch, image_ids: list[int], request_without_cursor: SearchRequest
) -> None:
    one_page = search.search(SearchRequest(**{**vars(request_without_cursor), "limit": 100})).image_ids

    assert all_pages(search, request_without_cursor) == one_page
    assert sorted(one_page) == sorted(image_ids)


def test_last_page_has_no_cursor(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    assert search.search(SearchRequest(limit=7)).next_cursor is None
    assert search.search(SearchRequest(limit=6)).next_cursor is not None


def test_new_image_does_not_shift_the_next_page(
    search: UnrestrictedSearch, database: Database, image_ids: list[int]
) -> None:
    first_page = search.search(SearchRequest(limit=3))
    add_image(database, 99, FIRST_DAY + timedelta(days=100))  # newer than everything

    second_page = search.search(SearchRequest(limit=3, cursor=first_page.next_cursor))

    assert second_page.image_ids == [image_ids[number] for number in (3, 2, 1)]


def test_paging_through_search_results(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    request = SearchRequest(query="category:artwork", limit=2)

    assert all_pages(search, request) == [image_ids[number] for number in (6, 4, 2, 0)]


# --- Random order

def test_same_seed_gives_the_same_order(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    first = search.search(SearchRequest(sort=Sort.RANDOM, seed=7)).image_ids

    assert search.search(SearchRequest(sort=Sort.RANDOM, seed=7)).image_ids == first
    assert search.search(SearchRequest(sort=Sort.RANDOM, seed=8)).image_ids != first


def test_random_order_needs_a_seed(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    assert invalid_field(lambda: search.search(SearchRequest(sort=Sort.RANDOM))) == "query.seed"


def test_shuffled_position_depends_on_seed_and_image() -> None:
    assert shuffled_position(1, 10) == shuffled_position(1, 10)
    assert shuffled_position(1, 10) != shuffled_position(2, 10)
    assert 0 <= shuffled_position(1, 10) < 2**56


# --- Cursors

@pytest.mark.parametrize("cursor", ["not base64!", "bm90IGpzb24", "eyJ2IjoxfQ", "eyJ2Ijoibm8gZGF0ZSIsImlkIjoxfQ"])
def test_damaged_cursor_is_refused(search: UnrestrictedSearch, image_ids: list[int], cursor: str) -> None:
    assert invalid_field(lambda: search.search(SearchRequest(cursor=cursor))) == "query.cursor"


def test_cursor_of_another_sort_is_refused(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    date_cursor = search.search(SearchRequest(limit=1)).next_cursor

    request = SearchRequest(sort=Sort.RANDOM, seed=1, cursor=date_cursor)

    assert invalid_field(lambda: search.search(request)) == "query.cursor"


# --- Hidden filters

def test_hidden_filters_are_applied_and_shown(search: UnrestrictedSearch, image_ids: list[int]) -> None:
    page = search.search(SearchRequest(query="year:2025", hidden_filters=("category:artwork",)))

    assert page.effective_query == "year:2025 -category:artwork"
    assert sorted(page.image_ids) == [image_ids[number] for number in (1, 3, 5)]
