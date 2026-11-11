# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The pictorio-db command."""

import argparse
import json
import sys

import uvicorn

from pictorio_db.app import create_app
from pictorio_db.config import ConfigError, config_from_environment


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pictorio-db", description="Image library server for Pictorio")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the server (settings: PICTORIO_* environment variables)")
    commands.add_parser("openapi", help="print the API schema, e.g. to update docs/openapi.json")

    command = parser.parse_args(arguments).command
    if command == "serve":
        return _serve()

    return _print_openapi()


def _serve() -> int:
    try:
        config = config_from_environment()
    except ConfigError as error:
        print(f"pictorio-db: {error}", file=sys.stderr)
        return 1

    # One process: the database and the background jobs assume it.
    uvicorn.run(create_app(), host=config.host, port=config.port)
    return 0


def _print_openapi() -> int:
    print(json.dumps(create_app().openapi(), indent=2))
    return 0
