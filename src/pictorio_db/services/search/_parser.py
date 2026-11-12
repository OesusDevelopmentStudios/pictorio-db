# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The search query language, parsed into a tree.

    query    := term ( WHITESPACE term )*                   terms are ANDed
    term     := [ "-" ] [ prefix ":" ] or_expr              no whitespace inside a term
    or_expr  := and_expr ( "|" and_expr )*
    and_expr := operand ( "," operand )*
    operand  := [ "-" ] [ prefix ":" ] ( "(" or_expr ")" | value )
    value    := name [ "*" ] | date [ ".." date ]
    prefix   := an existing namespace, or one of the date fields year, month, date

A value belongs to the nearest prefix to its left that encloses it, else to "general". A '-' at the start of
a term negates the whole term; inside a term, the operand right after it.
"""

import re
import unicodedata
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from pictorio_db.services.tags import GENERAL_NAMESPACE
from pictorio_db.utils.problems import Problem

DATE_FIELDS = frozenset({"year", "month", "date"})

_OPERATOR_CHARACTERS = ",|()"
_DATE_PATTERNS = {
    "year": re.compile(r"\d{4}"),
    "month": re.compile(r"\d{4}-\d{2}"),
    "date": re.compile(r"\d{4}-\d{2}-\d{2}"),
}
_DATE_EXAMPLES = {"year": "2025", "month": "2025-07", "date": "2025-07-14"}
_SPACE_IN_GROUP = "a space ends a term, so a group cannot contain spaces"


@dataclass(frozen=True)
class TagMatch:
    """A tag, or with `any_name_starting` every tag whose name starts with `name` ("" means any tag)."""

    namespace: str
    name: str
    any_name_starting: bool = False


@dataclass(frozen=True)
class DateMatch:
    """taken_at on a day from `first` to `last`, both included."""

    first: date
    last: date


@dataclass(frozen=True)
class Not:
    operand: "Node"


@dataclass(frozen=True)
class All:
    operands: tuple["Node", ...]  # no operands: every image


@dataclass(frozen=True)
class AnyOf:
    operands: tuple["Node", ...]


Node = TagMatch | DateMatch | Not | All | AnyOf


def parse_query(query: str, namespace_names: Collection[str]) -> All:
    """Raises 400 invalid_query with the 0-based `position` of the problem."""
    terms = [
        _TermParser(query, match.start(), match.end(), namespace_names).parse_term()
        for match in re.finditer(r"\S+", query)
    ]
    return All(tuple(terms))


class _TermParser:
    """Parses one term: query[start:end], which contains no whitespace."""

    def __init__(self, query: str, start: int, end: int, namespace_names: Collection[str]) -> None:
        self._query = query
        self._position = start
        self._end = end
        self._prefixes = set(namespace_names) | DATE_FIELDS
        self._open_groups = 0

    def parse_term(self) -> Node:
        node = self._term_body(GENERAL_NAMESPACE)
        if self._position < self._end:
            raise self._error(f"Unexpected '{self._peek()}'")

        return node

    def _term_body(self, namespace: str) -> Node:
        """[ "-" ] [ prefix ":" ] or_expr; the start of a term."""
        negated = self._consume("-")
        node = self._or_expression(self._prefix() or namespace)
        return Not(node) if negated else node

    def _or_expression(self, namespace: str) -> Node:
        operands = [self._and_expression(namespace)]
        while self._consume("|"):
            operands.append(self._and_expression(namespace))

        return operands[0] if len(operands) == 1 else AnyOf(tuple(operands))

    def _and_expression(self, namespace: str) -> Node:
        operands = [self._operand(namespace)]
        while self._consume(","):
            operands.append(self._operand(namespace))

        return operands[0] if len(operands) == 1 else All(tuple(operands))

    def _operand(self, namespace: str) -> Node:
        negated = self._consume("-")
        namespace = self._prefix() or namespace
        if self._consume("("):
            self._open_groups += 1
            node = self._or_expression(namespace)
            self._expect_closing_parenthesis()
            self._open_groups -= 1
        else:
            node = self._value(namespace)

        return Not(node) if negated else node

    def _prefix(self) -> str | None:
        """Reads "name:" if name is a namespace or a date field; anything else is part of a value."""
        name_end = self._position
        while name_end < self._end and self._query[name_end] not in _OPERATOR_CHARACTERS + ":*":
            name_end += 1

        name = self._query[self._position:name_end].lower()
        if name_end < self._end and self._query[name_end] == ":" and name in self._prefixes:
            self._position = name_end + 1
            return name

        return None

    def _value(self, namespace: str) -> Node:
        start = self._position
        while self._position < self._end and self._query[self._position] not in _OPERATOR_CHARACTERS:
            self._position += 1

        text = self._query[start:self._position]
        if not text:
            raise self._error("Expected a value", start)

        if namespace in DATE_FIELDS:
            return self._date_value(namespace, text, start)

        star = text.find("*")
        if star != -1 and star != len(text) - 1:
            raise self._error("'*' can only be at the end of a value", start + star)

        name = unicodedata.normalize("NFC", text.removesuffix("*")).lower()
        return TagMatch(namespace, name, any_name_starting=text.endswith("*"))

    def _date_value(self, field: str, text: str, start: int) -> DateMatch:
        first_text, separator, last_text = text.partition("..")
        first = self._date_period(field, first_text, start)
        last = self._date_period(field, last_text, start + len(first_text) + 2) if separator else first
        if last[1] < first[0]:
            raise self._error("The range ends before it starts", start)

        return DateMatch(first[0], last[1])

    def _date_period(self, field: str, text: str, start: int) -> tuple[date, date]:
        """The first and last day of a year, month or day."""
        if not _DATE_PATTERNS[field].fullmatch(text):
            raise self._error(f"Expected a {field} like {_DATE_EXAMPLES[field]}", start)

        parts = [int(part) for part in text.split("-")]
        try:
            if field == "year":
                return date(parts[0], 1, 1), date(parts[0], 12, 31)

            if field == "month":
                first_day = date(parts[0], parts[1], 1)
                next_month = date(parts[0] + parts[1] // 12, parts[1] % 12 + 1, 1)
                return first_day, date.fromordinal(next_month.toordinal() - 1)

            day = date(parts[0], parts[1], parts[2])
            return day, day
        except ValueError:
            raise self._error(f"No such {field}: {text}", start) from None

    def _expect_closing_parenthesis(self) -> None:
        if not self._consume(")"):
            raise self._error("Expected ')'")

    def _consume(self, character: str) -> bool:
        if self._peek() == character:
            self._position += 1
            return True

        return False

    def _peek(self) -> str:
        return self._query[self._position] if self._position < self._end else ""

    def _error(self, expected: str, position: int | None = None) -> Problem:
        position = self._position if position is None else position
        stopped_at_a_space = position == self._end and self._end < len(self._query)
        if stopped_at_a_space and self._open_groups > 0:
            expected = f"{expected}; {_SPACE_IN_GROUP}"

        return Problem(400, "invalid_query", "Invalid search query", expected, position=position)
