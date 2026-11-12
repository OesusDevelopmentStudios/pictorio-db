# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The pictorio-db command."""

import argparse
import json
import logging
import sys

import uvicorn

from pictorio_db.app import create_app
from pictorio_db.config import Config, ConfigError, config_from_environment


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pictorio-db", description="Image library server for Pictorio")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the server (settings: PICTORIO_* environment variables)")
    commands.add_parser("openapi", help="print the API schema, e.g. to update docs/openapi.json")

    command = parser.parse_args(arguments).command
    try:
        config = config_from_environment()
    except ConfigError as error:
        return _fail(str(error))

    if command == "serve":
        return _serve(config)

    return _print_openapi(config)


def _serve(config: Config) -> int:
    for description, folder in (("data folder", config.data_dir), ("library folder", config.library_dir)):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return _fail(f"cannot create the {description} {folder}: {error.strerror}")

    # Our messages appear in the same style as Uvicorn's, e.g. "WARNING:  ..."
    logging.basicConfig(level=logging.INFO, format="%(levelname)-9s %(message)s")

    # One process: the database and the background jobs assume it.
    uvicorn.run(create_app(config), host=config.host, port=config.port)
    return 0


def _print_openapi(config: Config) -> int:
    print(json.dumps(create_app(config).openapi(), indent=2))
    return 0


def _fail(message: str) -> int:
    print(f"pictorio-db: {message}", file=sys.stderr)
    return 1
