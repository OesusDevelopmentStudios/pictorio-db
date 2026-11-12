# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Tags and namespaces: name rules, splitting "namespace:name", autocomplete."""

from pictorio_db.services.tags._names import (
    GENERAL_NAMESPACE,
    RESERVED_NAMESPACE_NAMES,
    TagName,
    normalized_namespace_name,
    normalized_tag_name,
    split_tag,
)
from pictorio_db.services.tags._service import (
    DEFAULT_RATING_VALUES,
    MAX_RATING_VALUES,
    NamespaceInfo,
    TagCount,
    TagsService,
)

__all__ = [
    "DEFAULT_RATING_VALUES",
    "GENERAL_NAMESPACE",
    "MAX_RATING_VALUES",
    "NamespaceInfo",
    "RESERVED_NAMESPACE_NAMES",
    "TagCount",
    "TagName",
    "TagsService",
    "normalized_namespace_name",
    "normalized_tag_name",
    "split_tag",
]
