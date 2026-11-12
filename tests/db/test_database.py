# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from pictorio_db.db import DATABASE_FILE_NAME, Database, open_database
from pictorio_db.db._migrations import _alembic_config
from pictorio_db.db.models import Base, Image, Namespace, Tag, image_tag


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / DATABASE_FILE_NAME


@pytest.fixture
def database(database_path: Path) -> Iterator[Database]:
    opened_database = open_database(database_path)
    yield opened_database
    opened_database.close()


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def add_image_with_tag(database: Database) -> int:
    with database.session() as session:
        general = session.scalars(select(Namespace).where(Namespace.name == "general")).one()
        tag = Tag(namespace_id=general.id, name="summer")
        image = Image(
            sha256="ab" * 32,
            storage_path="photo/_unknown/2024/beach_abababab.jpg",
            original_filename="beach.jpg",
            mime_type="image/jpeg",
            width=40,
            height=30,
            file_size=1234,
            taken_at=now(),
            taken_at_source="import_time",
            imported_at=now(),
            updated_at=now(),
        )
        session.add_all([tag, image])
        session.flush()
        session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag.id))
        session.commit()
        return image.id


def test_creates_tables_in_empty_database(database: Database) -> None:
    table_names = set(inspect(database.engine).get_table_names())

    assert {"namespace", "tag", "image", "image_tag"} <= table_names


def test_adds_builtin_namespaces(database: Database) -> None:
    with database.session() as session:
        namespaces = {namespace.name: namespace for namespace in session.scalars(select(Namespace))}

    assert set(namespaces) == {"category", "author", "character", "rating", "album", "general"}
    assert all(namespace.is_builtin for namespace in namespaces.values())
    single_value_names = {name for name, namespace in namespaces.items() if namespace.single_value}
    assert single_value_names == {"category", "rating"}


def test_uses_write_ahead_log_and_foreign_keys(database: Database) -> None:
    with database.engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_opening_again_keeps_data(database_path: Path) -> None:
    first_opening = open_database(database_path)
    add_image_with_tag(first_opening)
    first_opening.close()

    second_opening = open_database(database_path)
    with second_opening.session() as session:
        image_count = len(session.scalars(select(Image)).all())
        namespace_count = len(session.scalars(select(Namespace)).all())
    second_opening.close()

    assert image_count == 1
    assert namespace_count == 6  # the built-in namespaces are not added twice


def test_models_match_migrations(database: Database) -> None:
    with database.engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == [], "The models differ from the migrations; add a migration for the change."


def test_migrations_can_be_undone_and_redone(database: Database) -> None:
    with database.engine.begin() as connection:
        command.downgrade(_alembic_config(connection), "base")
    assert "image" not in inspect(database.engine).get_table_names()

    with database.engine.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")
    assert "image" in inspect(database.engine).get_table_names()


def test_deleting_image_removes_its_tag_links(database: Database) -> None:
    image_id = add_image_with_tag(database)

    with database.session() as session:
        session.execute(delete(Image).where(Image.id == image_id))
        session.commit()
        remaining_links = session.execute(select(image_tag)).all()

    assert remaining_links == []


def test_tag_names_are_unique_within_a_namespace(database: Database) -> None:
    with database.session() as session:
        general = session.scalars(select(Namespace).where(Namespace.name == "general")).one()
        session.add_all([Tag(namespace_id=general.id, name="summer"), Tag(namespace_id=general.id, name="summer")])

        with pytest.raises(IntegrityError):
            session.commit()
