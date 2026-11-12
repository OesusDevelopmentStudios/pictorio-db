# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS_FOLDER = Path(__file__).parent / "migrations"


def upgrade_to_latest_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")


def _alembic_config(connection: object) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_FOLDER))
    config.attributes["connection"] = connection  # read by migrations/env.py
    return config
