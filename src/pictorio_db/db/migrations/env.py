# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Alembic environment: runs the migrations on the server's connection, or for the alembic command
on the database named in alembic.ini."""

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from pictorio_db.db.models import Base


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,  # SQLite can change most table definitions only by copying the table
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_for_alembic_command() -> None:
    engine = engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        run_migrations(connection)


server_connection = context.config.attributes.get("connection")
if server_connection is not None:
    run_migrations(server_connection)
else:
    run_migrations_for_alembic_command()
