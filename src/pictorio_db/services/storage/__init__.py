# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The library folder: where each image is stored, and moving files safely when their tags change."""

from pictorio_db.services.storage._paths import (
    DEFAULT_PATH_TEMPLATE,
    FOLDER_NAME_MAX_BYTES,
    UNKNOWN_FOLDER,
    VARIOUS_FOLDER,
    PathTemplate,
    file_name,
    folder_name,
    folder_path,
    parse_path_template,
)

__all__ = [
    "DEFAULT_PATH_TEMPLATE",
    "FOLDER_NAME_MAX_BYTES",
    "UNKNOWN_FOLDER",
    "VARIOUS_FOLDER",
    "PathTemplate",
    "file_name",
    "folder_name",
    "folder_path",
    "parse_path_template",
]
