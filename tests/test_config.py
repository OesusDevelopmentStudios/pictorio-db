# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

import pytest

from pictorio_db.config import DEFAULT_HOST, DEFAULT_PORT, Config, ConfigError, config_from_environment

HOME = {"HOME": "/home/user"}


def test_uses_defaults_without_environment_variables() -> None:
    assert config_from_environment(HOME) == Config(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        data_dir=Path("/home/user/.local/share/pictorio-db"),
        library_dir=Path("/home/user/Pictures/pictorio-library"),
    )


def test_reads_environment_variables() -> None:
    environment = HOME | {
        "PICTORIO_HOST": "0.0.0.0",
        "PICTORIO_PORT": "9000",
        "PICTORIO_DATA_DIR": "/data",
        "PICTORIO_LIBRARY_DIR": "/library",
        "PICTORIO_IMPORT_DIR": "/import",
    }

    assert config_from_environment(environment) == Config(
        host="0.0.0.0", port=9000, data_dir=Path("/data"), library_dir=Path("/library"), import_dir=Path("/import")
    )


def test_data_folder_follows_xdg_data_home() -> None:
    environment = HOME | {"XDG_DATA_HOME": "/home/user/data"}

    assert config_from_environment(environment).data_dir == Path("/home/user/data/pictorio-db")


@pytest.mark.parametrize("variable", ["PICTORIO_DATA_DIR", "PICTORIO_LIBRARY_DIR", "PICTORIO_IMPORT_DIR"])
def test_rejects_empty_folders(variable: str) -> None:
    with pytest.raises(ConfigError, match=variable):
        config_from_environment(HOME | {variable: ""})


@pytest.mark.parametrize("port_text", ["", "http", "-1", "0", "65536", "80.5"])
def test_rejects_invalid_port(port_text: str) -> None:
    with pytest.raises(ConfigError, match="PICTORIO_PORT"):
        config_from_environment(HOME | {"PICTORIO_PORT": port_text})
