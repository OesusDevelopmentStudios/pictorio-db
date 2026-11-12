# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError

from pictorio_db.db import Database
from pictorio_db.db.models import Namespace, Tag, image_tag
from pictorio_db.services.tags._names import (
    TagName,
    normalized_name_prefix,
    normalized_namespace_name,
    normalized_tag_name,
    split_tag,
)
from pictorio_db.utils.problems import Problem
from pictorio_db.utils.time import utc_now


@dataclass(frozen=True)
class NamespaceInfo:
    name: str
    single_value: bool
    is_builtin: bool
    in_path_template: bool  # its tags form folder names in the library


@dataclass(frozen=True)
class TagCount:
    tag: TagName
    image_count: int


# Sorts after every other character, so names from `prefix` up to `prefix + this` start with `prefix`.
_LAST_CHARACTER = "\U0010ffff"


class TagsService:
    """Namespaces and tags. `path_template_namespaces` returns the namespaces the library's path template
    uses; they cannot be deleted."""

    def __init__(self, database: Database, path_template_namespaces: Callable[[], frozenset[str]]) -> None:
        self._database = database
        self._path_template_namespaces = path_template_namespaces

    def parse_tag(self, text: str) -> TagName:
        """"Author:Polina Graff" → author:sample_artist. Raises 422 invalid_tag."""
        namespace, name = split_tag(text, self.namespace_names())
        return TagName(namespace, normalized_tag_name(name))

    def autocomplete(self, prefix: str = "", namespace: str | None = None, limit: int = 20) -> list[TagCount]:
        """Tags starting with `prefix`, most used first. "author:pol" searches one namespace, "pol" all of them.
        `image_count` counts all images, also ones a restricted user cannot see."""
        prefix_namespace, name_prefix = self._split_prefix(prefix)
        namespaces = {name for name in (prefix_namespace, namespace and namespace.lower()) if name}
        if len(namespaces) > 1:
            return []  # the namespace filter and the prefix's namespace disagree

        image_count = func.count(image_tag.c.image_id)
        query = (
            select(Namespace.name, Tag.name, image_count)
            .join(Namespace, Tag.namespace_id == Namespace.id)
            .outerjoin(image_tag, image_tag.c.tag_id == Tag.id)
            .group_by(Tag.id)
            .order_by(image_count.desc(), Namespace.name, Tag.name)
            .limit(limit)
        )
        if namespaces:
            query = query.where(Namespace.name == namespaces.pop())

        if name_prefix:
            query = query.where(Tag.name >= name_prefix, Tag.name < name_prefix + _LAST_CHARACTER)

        with self._database.session() as session:
            return [
                TagCount(TagName(namespace_name, tag_name), count)
                for namespace_name, tag_name, count in session.execute(query)
            ]

    def _split_prefix(self, prefix: str) -> tuple[str | None, str]:
        """Like split_tag, but text without a namespace searches all namespaces instead of general only."""
        namespace, separator, rest = prefix.partition(":")
        if separator and namespace.strip().lower() in self.namespace_names():
            return namespace.strip().lower(), normalized_name_prefix(rest)

        return None, normalized_name_prefix(prefix)

    # --- Namespaces

    def namespace_names(self) -> set[str]:
        with self._database.session() as session:
            return set(session.scalars(select(Namespace.name)))

    def list_namespaces(self) -> list[NamespaceInfo]:
        """Built-in namespaces first, then the others in the order they were created."""
        path_namespaces = self._path_template_namespaces()
        with self._database.session() as session:
            namespaces = session.scalars(select(Namespace).order_by(Namespace.id))
            return [_namespace_info(namespace, path_namespaces) for namespace in namespaces]

    def create_namespace(self, name: str, single_value: bool) -> NamespaceInfo:
        name = normalized_namespace_name(name)
        namespace = Namespace(name=name, single_value=single_value, is_builtin=False, created_at=utc_now())
        with self._database.session() as session:
            session.add(namespace)
            try:
                session.commit()
            except IntegrityError:
                raise Problem(
                    409, "already_exists", "Namespace exists", f"A namespace {name!r} exists already."
                ) from None

            return _namespace_info(namespace, self._path_template_namespaces())

    def delete_namespace(self, name: str) -> None:
        """Only custom namespaces that no tag and no path template uses."""
        with self._database.session() as session:
            namespace = session.scalars(select(Namespace).where(Namespace.name == name)).one_or_none()
            if namespace is None:
                raise Problem(404, "not_found", "Namespace not found")

            has_tags = bool(session.scalar(select(exists().where(Tag.namespace_id == namespace.id))))
            reason = self._reason_namespace_is_in_use(namespace, has_tags)
            if reason is not None:
                raise Problem(409, "namespace_in_use", "Namespace is in use", reason)

            session.delete(namespace)
            session.commit()

    def _reason_namespace_is_in_use(self, namespace: Namespace, has_tags: bool) -> str | None:
        if namespace.is_builtin:
            return "Built-in namespaces cannot be deleted."

        if namespace.name in self._path_template_namespaces():
            return "The library's path template uses this namespace."

        if has_tags:
            return "Tags in this namespace exist; rename or delete them first."

        return None


def _namespace_info(namespace: Namespace, path_namespaces: frozenset[str]) -> NamespaceInfo:
    return NamespaceInfo(
        name=namespace.name,
        single_value=namespace.single_value,
        is_builtin=namespace.is_builtin,
        in_path_template=namespace.name in path_namespaces,
    )
