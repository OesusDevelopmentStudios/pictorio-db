# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""One test per rule of the library layout: path template, folder names, file names."""

from datetime import datetime
from pathlib import PurePosixPath

import pytest

from pictorio_db.services.storage import (
    DEFAULT_PATH_TEMPLATE,
    PathTemplate,
    file_name,
    folder_name,
    folder_path,
    parse_path_template,
)
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}
TAKEN_AT = datetime(2025, 7, 14, 18, 30)
SHA256 = "3fa2b1c9" + "0" * 56


def template(text: str) -> PathTemplate:
    return parse_path_template(text, NAMESPACES)


def template_problem(text: str) -> str:
    with pytest.raises(Problem) as raised:
        template(text)

    assert (raised.value.status, raised.value.code) == (422, "validation_error")
    error = raised.value.extra["errors"][0]
    assert error["field"] == "path_template"
    return error["message"]


# --- Path template

def test_default_template_uses_category_and_author() -> None:
    assert template(DEFAULT_PATH_TEMPLATE).namespaces == {"category", "author"}


def test_folder_can_mix_placeholders_and_fixed_text() -> None:
    path = folder_path(template("photos/{year}-{month}"), {}, TAKEN_AT)

    assert path == PurePosixPath("photos/2025-07")


def test_empty_template_stores_files_in_the_library_folder() -> None:
    assert folder_path(template(""), {}, TAKEN_AT) == PurePosixPath(".")


def test_rejects_unknown_placeholders() -> None:
    assert "Unknown placeholder {weather}" in template_problem("{category}/{weather}")


@pytest.mark.parametrize("text", ["{category}//{year}", "/{category}", "{category}/", "./{year}", "{year}/.."])
def test_rejects_empty_and_dot_folders(text: str) -> None:
    assert "cannot be empty, '.' or '..'" in template_problem(text)


@pytest.mark.parametrize("text", ["{category}\\{year}", "{year}}", "a{b", "{year}\t"])
def test_rejects_characters_that_do_not_belong_in_a_path(text: str) -> None:
    message = template_problem(text)

    assert "cannot contain" in message or "Unknown placeholder" in message


# --- Folder names

def test_folder_is_the_tag_name() -> None:
    tags = {"category": ["artwork"], "author": ["sample_artist"]}

    path = folder_path(template(DEFAULT_PATH_TEMPLATE), tags, TAKEN_AT)

    assert path == PurePosixPath("artwork/sample_artist/2025")


def test_missing_tag_gives_unknown_folder() -> None:
    path = folder_path(template(DEFAULT_PATH_TEMPLATE), {"category": ["photo"]}, TAKEN_AT)

    assert path == PurePosixPath("photo/_unknown/2025")


def test_several_tags_give_various_folder() -> None:
    tags = {"category": ["artwork"], "author": ["first_artist", "second_artist"]}

    assert folder_path(template(DEFAULT_PATH_TEMPLATE), tags, TAKEN_AT) == PurePosixPath("artwork/_various/2025")


def test_month_has_two_digits() -> None:
    assert folder_path(template("{month}"), {}, datetime(2025, 3, 1)) == PurePosixPath("03")


def test_leading_dot_becomes_underscore() -> None:
    assert folder_name(".hidden") == "_hidden"


def test_folder_name_is_cut_to_100_bytes_between_characters() -> None:
    name = "a" * 99 + "ą"  # 'ą' takes two bytes, so it no longer fits

    assert folder_name(name) == "a" * 99
    assert len(folder_name("b" * 150).encode()) == 100


# --- File names

def test_file_name_is_stem_hash_and_detected_extension() -> None:
    assert file_name("IMG_2041.JPG", SHA256, "jpg") == "IMG_2041_3fa2b1c9.jpg"


def test_file_without_extension_gets_one() -> None:
    assert file_name("scan", SHA256, "png") == "scan_3fa2b1c9.png"


@pytest.mark.parametrize("original", ["C:\\photos\\beach.jpg", "/home/user/beach.jpg", "../beach.jpg"])
def test_only_the_last_part_of_a_path_counts(original: str) -> None:
    assert file_name(original, SHA256, "jpg") == "beach_3fa2b1c9.jpg"


@pytest.mark.parametrize(("original", "expected"), [(".beach.jpg", "beach"), (".jpg", "jpg")])
def test_hidden_file_name_is_not_hidden_in_the_library(original: str, expected: str) -> None:
    assert file_name(original, SHA256, "jpg") == f"{expected}_3fa2b1c9.jpg"


def test_control_characters_become_underscores() -> None:
    assert file_name("bad\nname.jpg", SHA256, "jpg") == "bad_name_3fa2b1c9.jpg"


@pytest.mark.parametrize("original", ["", "...", "  .png"])
def test_empty_stem_gets_a_fallback_name(original: str) -> None:
    assert file_name(original, SHA256, "png") == "image_3fa2b1c9.png"


def test_long_stem_is_cut_to_200_bytes() -> None:
    name = file_name("x" * 300 + ".jpg", SHA256, "jpg")

    assert name == "x" * 200 + "_3fa2b1c9.jpg"
    assert len(name.encode()) <= 255
