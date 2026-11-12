# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Where an image is stored in the library: folders from the path template, a file name from the
original name and the image's SHA-256."""

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from pictorio_db.utils.problems import Problem

DEFAULT_PATH_TEMPLATE = "{category}/{author}/{year}"
DATE_PLACEHOLDERS = frozenset({"year", "month"})

UNKNOWN_FOLDER = "_unknown"  # the image has no tag in the namespace
VARIOUS_FOLDER = "_various"  # the image has several tags in the namespace, e.g. two authors

FOLDER_NAME_MAX_BYTES = 100
FILE_STEM_MAX_BYTES = 200  # with the hash and the extension, below the usual 255-byte limit
FALLBACK_FILE_STEM = "image"
HASH_LENGTH_IN_FILE_NAME = 8

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


@dataclass(frozen=True)
class Placeholder:
    name: str


@dataclass(frozen=True)
class PathTemplate:
    """Folders separated by '/'; each folder is fixed text and placeholders, e.g. "{year}-{month}"."""

    text: str
    folders: tuple[tuple[str | Placeholder, ...], ...]

    @property
    def namespaces(self) -> frozenset[str]:
        """The namespaces whose tags form folder names."""
        return frozenset(
            part.name
            for folder in self.folders
            for part in folder
            if isinstance(part, Placeholder) and part.name not in DATE_PLACEHOLDERS
        )


def parse_path_template(text: str, namespace_names: Collection[str]) -> PathTemplate:
    """Raises 422 validation_error for unknown placeholders and text that cannot be part of a path."""
    if not text:
        return PathTemplate(text, ())  # every file directly in the library folder

    allowed_placeholders = set(namespace_names) | DATE_PLACEHOLDERS
    folders = tuple(_parse_folder(folder_text, allowed_placeholders) for folder_text in text.split("/"))
    return PathTemplate(text, folders)


def folder_path(template: PathTemplate, tags: Mapping[str, Sequence[str]], taken_at: datetime) -> PurePosixPath:
    """The folder of an image, relative to the library. `tags` maps a namespace to the image's tag names."""
    return PurePosixPath(*(_render_folder(folder, tags, taken_at) for folder in template.folders))


def file_name(original_filename: str, sha256: str, extension: str) -> str:
    """'<original stem>_<first 8 hex digits of the SHA-256>.<extension>': readable, and unique in practice.
    The extension comes from the detected image type, not from the original name."""
    return f"{_file_stem(original_filename)}_{sha256[:HASH_LENGTH_IN_FILE_NAME]}.{extension}"


def folder_name(text: str) -> str:
    """A leading '.' would hide the folder, so it becomes '_'; at most FOLDER_NAME_MAX_BYTES."""
    if text.startswith("."):
        text = "_" + text[1:]

    return _cut_to_bytes(text, FOLDER_NAME_MAX_BYTES)


def _parse_folder(folder_text: str, allowed_placeholders: set[str]) -> tuple[str | Placeholder, ...]:
    if folder_text in ("", ".", ".."):
        raise _invalid_template(f"Folder names cannot be empty, '.' or '..': {folder_text!r}")

    parts: list[str | Placeholder] = []
    position = 0
    for match in _PLACEHOLDER.finditer(folder_text):
        parts.extend(_fixed_text(folder_text[position:match.start()]))
        name = match.group(1)
        if name not in allowed_placeholders:
            raise _invalid_template(f"Unknown placeholder {{{name}}}: use a namespace, {{year}} or {{month}}")

        parts.append(Placeholder(name))
        position = match.end()

    parts.extend(_fixed_text(folder_text[position:]))
    return tuple(parts)


def _fixed_text(text: str) -> list[str]:
    if any(character in "{}\\" or unicodedata.category(character) == "Cc" for character in text):
        raise _invalid_template(f"Fixed text cannot contain '{{', '}}', '\\' or control characters: {text!r}")

    return [text] if text else []


def _render_folder(folder: tuple[str | Placeholder, ...], tags: Mapping[str, Sequence[str]], taken_at: datetime) -> str:
    rendered = "".join(
        part if isinstance(part, str) else _placeholder_value(part.name, tags, taken_at) for part in folder
    )
    return folder_name(rendered)


def _placeholder_value(name: str, tags: Mapping[str, Sequence[str]], taken_at: datetime) -> str:
    if name == "year":
        return f"{taken_at.year:04}"

    if name == "month":
        return f"{taken_at.month:02}"

    tag_names = tags.get(name, ())
    if not tag_names:
        return UNKNOWN_FOLDER

    if len(tag_names) > 1:
        return VARIOUS_FOLDER

    return tag_names[0]


def _file_stem(original_filename: str) -> str:
    """The original name without folders and extension, safe as part of a file name."""
    last_part = re.split(r"[/\\]", original_filename)[-1]
    stem = last_part.rsplit(".", 1)[0] if "." in last_part.lstrip(".") else last_part
    stem = "".join("_" if unicodedata.category(character) == "Cc" else character for character in stem)
    stem = _cut_to_bytes(stem.lstrip(".").strip(), FILE_STEM_MAX_BYTES)
    return stem or FALLBACK_FILE_STEM


def _cut_to_bytes(text: str, max_bytes: int) -> str:
    """At most max_bytes in UTF-8, cut between characters, never inside one."""
    return text.encode()[:max_bytes].decode(errors="ignore")


def _invalid_template(message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": "path_template", "message": message}],
    )
