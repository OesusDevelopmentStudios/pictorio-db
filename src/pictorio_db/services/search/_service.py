# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import base64
import binascii
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, and_, func, or_, select

from pictorio_db.db import Database
from pictorio_db.db.models import Image
from pictorio_db.services.search._conditions import matching_condition
from pictorio_db.services.search._hidden_filters import apply_hidden_filters
from pictorio_db.services.search._parser import parse_query
from pictorio_db.utils.problems import Problem

DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class Sort(StrEnum):
    TAKEN_AT = "taken_at"
    IMPORTED_AT = "imported_at"
    RANDOM = "random"


class Order(StrEnum):
    DESC = "desc"
    ASC = "asc"


@dataclass(frozen=True)
class SearchRequest:
    query: str = ""
    sort: Sort = Sort.TAKEN_AT
    order: Order = Order.DESC  # ignored for random
    seed: int | None = None  # required for random
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None  # next_cursor of the previous page
    hidden_filters: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchPage:
    image_ids: list[int]
    next_cursor: str | None  # None on the last page
    effective_query: str  # the query with the hidden filters that were added


class SearchService:
    """Searches images with the query language. Pages are found by "keyset": each page continues after the
    sort value and id of the previous page's last image, so pages stay correct while images are added."""

    def __init__(self, database: Database, namespace_names: Callable[[], Collection[str]]) -> None:
        self._database = database
        self._namespace_names = namespace_names

    def search(self, request: SearchRequest) -> SearchPage:
        """Raises 400 invalid_query, or 422 validation_error for a missing seed or a damaged cursor."""
        namespace_names = self._namespace_names()
        tree = parse_query(request.query, namespace_names)
        filtered = apply_hidden_filters(request.query, tree, list(request.hidden_filters), namespace_names)

        sort_value = _sort_value(request.sort, request.seed)
        descending = request.sort != Sort.RANDOM and request.order == Order.DESC
        statement = select(Image.id, sort_value).where(matching_condition(filtered.tree))
        if request.cursor is not None:
            last_value, last_id = _decode_cursor(request.cursor, request.sort)
            statement = statement.where(_after(sort_value, last_value, last_id, descending))

        sort_order = (sort_value.desc(), Image.id.desc()) if descending else (sort_value.asc(), Image.id.asc())
        statement = statement.order_by(*sort_order).limit(request.limit + 1)  # one more: is there a next page?

        with self._database.session() as session:
            rows = session.execute(statement).all()

        page_rows = rows[: request.limit]
        has_next_page = len(rows) > request.limit
        next_cursor = _encode_cursor(page_rows[-1][1], page_rows[-1][0]) if has_next_page else None
        return SearchPage([image_id for image_id, _value in page_rows], next_cursor, filtered.effective_query)


def _sort_value(sort: Sort, seed: int | None) -> ColumnElement:
    if sort == Sort.RANDOM:
        if seed is None:
            raise _invalid("query.seed", "Required for sort=random; the same seed gives the same order.")

        return func.shuffled_position(seed, Image.id)  # registered on every database connection

    return Image.taken_at if sort == Sort.TAKEN_AT else Image.imported_at


def _after(sort_value: ColumnElement, last_value: object, last_id: int, descending: bool) -> ColumnElement[bool]:
    if descending:
        return or_(sort_value < last_value, and_(sort_value == last_value, Image.id < last_id))

    return or_(sort_value > last_value, and_(sort_value == last_value, Image.id > last_id))


def _encode_cursor(sort_value: object, image_id: int) -> str:
    """base64url JSON {"v": <last sort value>, "id": <last id>}, as the API documents it."""
    value = sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value
    text = json.dumps({"v": value, "id": image_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, sort: Sort) -> tuple[object, int]:
    try:
        content = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        image_id = content["id"]
        value = content["v"]
        if not isinstance(image_id, int):
            raise ValueError

        if sort == Sort.RANDOM:
            if not isinstance(value, int):
                raise ValueError

            return value, image_id

        return datetime.fromisoformat(value), image_id
    except (binascii.Error, ValueError, TypeError, KeyError, UnicodeDecodeError):
        raise _invalid("query.cursor", "Use next_cursor of the previous page, with the same sort.") from None


def _invalid(field: str, message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": field, "message": message}],
    )
