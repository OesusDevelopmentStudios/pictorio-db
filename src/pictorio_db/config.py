# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Settings read from environment variables when the server starts."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"  # only this computer; the container image sets 0.0.0.0
DEFAULT_PORT = 8737


class ConfigError(Exception):
    """An environment variable has a value the server cannot use."""


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    data_dir: Path  # the database and, later, thumbnails; the container image sets /data


def config_from_environment(environment: Mapping[str, str] = os.environ) -> Config:
    return Config(
        host=environment.get("PICTORIO_HOST", DEFAULT_HOST),
        port=_parse_port(environment.get("PICTORIO_PORT", str(DEFAULT_PORT))),
        data_dir=_data_dir(environment),
    )


def _parse_port(text: str) -> int:
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise ConfigError(f"PICTORIO_PORT must be a number from 1 to 65535, not {text!r}")

    return int(text)


# Without PICTORIO_DATA_DIR: ~/.local/share/pictorio-db, or the same under XDG_DATA_HOME if it is set.
def _data_dir(environment: Mapping[str, str]) -> Path:
    if "PICTORIO_DATA_DIR" in environment:
        if not environment["PICTORIO_DATA_DIR"]:
            raise ConfigError("PICTORIO_DATA_DIR must not be empty")

        return Path(environment["PICTORIO_DATA_DIR"]).expanduser().absolute()

    home = Path(environment.get("HOME", str(Path.home())))
    data_home = Path(environment.get("XDG_DATA_HOME") or home / ".local" / "share")
    return data_home / "pictorio-db"
