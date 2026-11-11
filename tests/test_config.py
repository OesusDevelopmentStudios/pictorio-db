# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import pytest

from pictorio_db.config import DEFAULT_HOST, DEFAULT_PORT, Config, ConfigError, config_from_environment


def test_uses_defaults_without_environment_variables() -> None:
    assert config_from_environment({}) == Config(host=DEFAULT_HOST, port=DEFAULT_PORT)


def test_reads_environment_variables() -> None:
    environment = {"PICTORIO_HOST": "0.0.0.0", "PICTORIO_PORT": "9000"}

    assert config_from_environment(environment) == Config(host="0.0.0.0", port=9000)


@pytest.mark.parametrize("port_text", ["", "http", "-1", "0", "65536", "80.5"])
def test_rejects_invalid_port(port_text: str) -> None:
    with pytest.raises(ConfigError, match="PICTORIO_PORT"):
        config_from_environment({"PICTORIO_PORT": port_text})
