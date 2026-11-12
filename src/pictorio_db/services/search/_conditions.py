# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""A parsed query as a condition on the image table."""

from datetime import datetime, time, timedelta

from sqlalchemy import ColumnElement, and_, not_, or_, select, true

from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.search._parser import All, DateMatch, Node, Not, TagMatch

# Sorts after every other character: names from `prefix` up to `prefix + this` start with `prefix`.
_LAST_CHARACTER = "\U0010ffff"


def matching_condition(node: Node) -> ColumnElement[bool]:
    if isinstance(node, TagMatch):
        return _has_tag(node)

    if isinstance(node, DateMatch):
        return _taken_within(node)

    if isinstance(node, Not):
        return not_(matching_condition(node.operand))

    if isinstance(node, All):
        return and_(true(), *(matching_condition(operand) for operand in node.operands))

    return or_(*(matching_condition(operand) for operand in node.operands))


def _has_tag(match: TagMatch) -> ColumnElement[bool]:
    """Finds the matching tags first, then their images: both steps use an index."""
    matching_tags = select(Tag.id).join(Namespace, Tag.namespace_id == Namespace.id).where(
        Namespace.name == match.namespace
    )
    if match.any_name_starting:
        if match.name:  # not LIKE: '_' is in many tag names and would be a wildcard there
            matching_tags = matching_tags.where(Tag.name >= match.name, Tag.name < match.name + _LAST_CHARACTER)
    else:
        matching_tags = matching_tags.where(Tag.name == match.name)

    images_with_tag = select(image_tag.c.image_id).where(image_tag.c.tag_id.in_(matching_tags))
    return Image.id.in_(images_with_tag)


def _taken_within(match: DateMatch) -> ColumnElement[bool]:
    start = datetime.combine(match.first, time.min)
    end = datetime.combine(match.last + timedelta(days=1), time.min)
    return and_(Image.taken_at >= start, Image.taken_at < end)
