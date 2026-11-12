# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

import pytest

from pictorio_db.db import Database
from pictorio_db.services.settings import SettingsService
from pictorio_db.services.storage import DEFAULT_PATH_TEMPLATE, StorageService
from pictorio_db.utils.problems import Problem

NAMESPACES = {"category", "author", "character", "rating", "album", "general"}


@pytest.fixture
def namespaces() -> set[str]:
    return set(NAMESPACES)


@pytest.fixture
def storage(database: Database, tmp_path: Path, namespaces: set[str]) -> StorageService:
    return StorageService(SettingsService(database), tmp_path / "library", lambda: namespaces)


def test_uses_the_default_template_until_one_is_set(storage: StorageService) -> None:
    assert storage.path_template().text == DEFAULT_PATH_TEMPLATE
    assert storage.path_template_namespaces() == {"category", "author"}


def test_keeps_a_new_template(storage: StorageService) -> None:
    storage.set_path_template(" {album}/{year}-{month} ")

    assert storage.path_template().text == "{album}/{year}-{month}"
    assert storage.path_template_namespaces() == {"album"}


def test_invalid_template_keeps_the_previous_one(storage: StorageService) -> None:
    storage.set_path_template("{album}")

    with pytest.raises(Problem):
        storage.set_path_template("{weather}")

    assert storage.path_template().text == "{album}"


def test_new_namespace_can_be_used_in_the_template(storage: StorageService, namespaces: set[str]) -> None:
    namespaces.add("weather")

    storage.set_path_template("{weather}/{year}")

    assert storage.path_template_namespaces() == {"weather"}
