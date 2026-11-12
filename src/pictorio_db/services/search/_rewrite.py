# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Changing stored terms (restrictions, hidden filters) after an admin renamed or deleted a tag. A term that
does not name the tag keeps its text as written. Wildcards are patterns, not tags, so they are left alone."""

from collections.abc import Collection

from pictorio_db.services.search._parser import All, AnyOf, DateMatch, Node, Not, TagMatch, parse_query
from pictorio_db.services.tags import TagName


def renamed_in_term(term: str, old_tag: TagName, new_tag: TagName, namespace_names: Collection[str]) -> str:
    """The term naming new_tag wherever it named old_tag."""
    tree = _parse_term(term, namespace_names)
    if not _names_tag(tree, old_tag):
        return term

    return term_text(_renamed(tree, old_tag, new_tag))


def without_tag_in_term(term: str, tag: TagName, namespace_names: Collection[str]) -> str | None:
    """None if the term goes. In an OR only the tag goes (rating:nsfw|questionable → rating:questionable); a term
    that names the tag in any other way can no longer match as written, so it goes whole."""
    tree = _parse_term(term, namespace_names)
    if not _names_tag(tree, tag):
        return term

    remaining = _without(tree, tag)
    return None if remaining is None else term_text(remaining)


def term_text(node: Node) -> str:
    """One term that parses back to the same tree. Every tag is written with its namespace."""
    if isinstance(node, Not):
        return f"({_text(node)})"  # a leading '-' would be refused in a stored term

    return _text(node)


def _text(node: Node) -> str:
    if isinstance(node, TagMatch):
        return f"{node.namespace}:{node.name}{'*' if node.any_name_starting else ''}"

    if isinstance(node, DateMatch):
        last = "" if node.last == node.first else f"..{node.last.isoformat()}"
        return f"date:{node.first.isoformat()}{last}"

    if isinstance(node, Not):
        return f"-{_grouped(node.operand)}"

    if isinstance(node, All):
        # ',' binds more tightly than '|'; groups inside groups keep their parentheses, so the tree stays the same
        return ",".join(_grouped(part) for part in node.operands)

    assert isinstance(node, AnyOf)
    return "|".join(f"({_text(part)})" if isinstance(part, AnyOf) else _text(part) for part in node.operands)


def _grouped(node: Node) -> str:
    return f"({_text(node)})" if isinstance(node, (All, AnyOf)) else _text(node)


def _parse_term(term: str, namespace_names: Collection[str]) -> Node:
    [tree] = parse_query(term, namespace_names).operands  # a stored term is one term
    return tree


def _is_tag(node: Node, tag: TagName) -> bool:
    return isinstance(node, TagMatch) and not node.any_name_starting and TagName(node.namespace, node.name) == tag


def _names_tag(node: Node, tag: TagName) -> bool:
    if isinstance(node, Not):
        return _names_tag(node.operand, tag)

    if isinstance(node, (All, AnyOf)):
        return any(_names_tag(operand, tag) for operand in node.operands)

    return _is_tag(node, tag)


def _renamed(node: Node, old_tag: TagName, new_tag: TagName) -> Node:
    if _is_tag(node, old_tag):
        return TagMatch(new_tag.namespace, new_tag.name)

    if isinstance(node, Not):
        return Not(_renamed(node.operand, old_tag, new_tag))

    if isinstance(node, (All, AnyOf)):
        operands = tuple(dict.fromkeys(_renamed(operand, old_tag, new_tag) for operand in node.operands))
        return operands[0] if len(operands) == 1 else type(node)(operands)

    return node


def _without(node: Node, tag: TagName) -> Node | None:
    """None: the node goes."""
    if _is_tag(node, tag):
        return None

    if isinstance(node, Not):
        operand = _without(node.operand, tag)
        return None if operand is None else Not(operand)

    if isinstance(node, All):
        operands = [_without(operand, tag) for operand in node.operands]
        return None if None in operands else All(tuple(operands))  # type: ignore[arg-type]

    if isinstance(node, AnyOf):
        operands = [kept for kept in (_without(operand, tag) for operand in node.operands) if kept is not None]
        if not operands:
            return None

        return operands[0] if len(operands) == 1 else AnyOf(tuple(operands))

    return node
