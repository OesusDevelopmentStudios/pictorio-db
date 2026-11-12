# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Hidden-by-default filters: each user's filters (e.g. rating:nsfw) hide images from the default view, but
searching for one of the filter's tags shows them again."""

from collections.abc import Collection
from dataclasses import dataclass

from pictorio_db.services.search._parser import All, AnyOf, Node, Not, TagMatch, parse_query


@dataclass(frozen=True)
class FilteredQuery:
    tree: All
    effective_query: str  # what was actually searched, shown to the user


def apply_hidden_filters(
    query: str, tree: All, hidden_filters: list[str], namespace_names: Collection[str]
) -> FilteredQuery:
    """Adds -<filter> for each filter, unless the query mentions a tag that the filter mentions,
    positively or negatively."""
    query_tags = mentioned_tags(tree)
    terms = list(tree.operands)
    effective_terms = [query.strip()] if query.strip() else []
    for hidden_filter in hidden_filters:
        filter_tree = parse_query(hidden_filter, namespace_names)
        if _overlap(query_tags, mentioned_tags(filter_tree)):
            continue

        terms.append(Not(filter_tree))
        effective_terms.append(f"-{hidden_filter}")

    return FilteredQuery(All(tuple(terms)), " ".join(effective_terms))


def mentioned_tags(node: Node) -> list[TagMatch]:
    if isinstance(node, TagMatch):
        return [node]

    if isinstance(node, Not):
        return mentioned_tags(node.operand)

    if isinstance(node, All | AnyOf):
        return [tag for operand in node.operands for tag in mentioned_tags(operand)]

    return []  # a date


def _overlap(query_tags: list[TagMatch], filter_tags: list[TagMatch]) -> bool:
    return any(_same_tags(query_tag, filter_tag) for query_tag in query_tags for filter_tag in filter_tags)


def _same_tags(first: TagMatch, second: TagMatch) -> bool:
    """Whether two matches can name a common tag: character:* and character:geralt can."""
    if first.namespace != second.namespace:
        return False

    if first.any_name_starting and second.name.startswith(first.name):
        return True

    if second.any_name_starting and first.name.startswith(second.name):
        return True

    return first.name == second.name
