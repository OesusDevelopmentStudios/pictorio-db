# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Settings read from environment variables when the server starts."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"  # only this computer; the container image sets 0.0.0.0
DEFAULT_PORT = 8737


class ConfigError(Exception):
    """An environment variable has a value the server cannot use."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int


def config_from_environment(environment: Mapping[str, str] = os.environ) -> Config:
    return Config(
        host=environment.get("PICTORIO_HOST", DEFAULT_HOST),
        port=_parse_port(environment.get("PICTORIO_PORT", str(DEFAULT_PORT))),
    )


def _parse_port(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ConfigError(f"PICTORIO_PORT must be a number from 1 to 65535, not {text!r}")

    return int(text)
