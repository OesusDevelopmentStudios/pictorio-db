# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Bringing images into the library: what a file is, whether it is new, and storing it with its tags."""

from pictorio_db.services.importer._inspection import (
    SUPPORTED_TYPES,
    ImageFacts,
    ImageType,
    file_sha256,
    inspect_image,
)
from pictorio_db.services.importer._service import (
    DEFAULT_MAX_UPLOAD_BYTES,
    MAX_UPLOAD_BYTES_SETTING,
    UPLOAD_LIMIT_RANGE,
    ImporterService,
    UploadMetadata,
    check_upload_limit,
)

__all__ = [
    "DEFAULT_MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_BYTES_SETTING",
    "SUPPORTED_TYPES",
    "UPLOAD_LIMIT_RANGE",
    "ImageFacts",
    "ImageType",
    "ImporterService",
    "UploadMetadata",
    "check_upload_limit",
    "file_sha256",
    "inspect_image",
]
