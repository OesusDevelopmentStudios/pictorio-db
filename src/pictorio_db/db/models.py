# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Database tables. Schema changes are made only through migrations (db/migrations/versions/)."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, Index, MetaData, String, Table, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Fixed constraint names, so that later migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

NAMESPACE_NAME_MAX_LENGTH = 32
USERNAME_MAX_LENGTH = 32
ROLES = ("admin", "user")
TAG_NAME_MAX_LENGTH = 100
TAKEN_AT_SOURCES = ("exif", "file_mtime", "import_time")
_TAKEN_AT_SOURCES_SQL = ", ".join(f"'{source}'" for source in TAKEN_AT_SOURCES)
_ROLES_SQL = ", ".join(f"'{role}'" for role in ROLES)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Namespace(Base):
    """The part before ':' in a tag, e.g. 'author' in 'author:sample_artist'."""

    __tablename__ = "namespace"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(NAMESPACE_NAME_MAX_LENGTH), unique=True)
    single_value: Mapped[bool]  # a second tag in this namespace replaces the first one
    is_builtin: Mapped[bool]  # built-in namespaces cannot be deleted or renamed
    created_at: Mapped[datetime]


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("namespace_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    namespace_id: Mapped[int] = mapped_column(ForeignKey("namespace.id"))
    name: Mapped[str] = mapped_column(String(TAG_NAME_MAX_LENGTH))


class Image(Base):
    __tablename__ = "image"
    __table_args__ = (
        CheckConstraint(f"taken_at_source IN ({_TAKEN_AT_SOURCES_SQL})", name="taken_at_source"),
        # Keyset pagination sorts by these columns, with the id as tie-breaker.
        Index(None, "taken_at", "id"),
        Index(None, "imported_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    storage_path: Mapped[str] = mapped_column(unique=True)  # relative to the library folder
    original_filename: Mapped[str]
    mime_type: Mapped[str]
    width: Mapped[int]
    height: Mapped[int]
    file_size: Mapped[int]
    taken_at: Mapped[datetime]  # local wall-clock time, as EXIF records it; no time zone
    taken_at_source: Mapped[str]  # one of TAKEN_AT_SOURCES
    taken_at_utc_offset_minutes: Mapped[int | None]  # from EXIF OffsetTimeOriginal, if present
    imported_at: Mapped[datetime]  # UTC
    updated_at: Mapped[datetime]  # UTC


image_tag = Table(
    "image_tag",
    Base.metadata,
    Column("image_id", ForeignKey("image.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id"), primary_key=True),
    Index(None, "tag_id", "image_id"),  # finds the images with a tag
)


class User(Base):
    __tablename__ = "user"
    __table_args__ = (CheckConstraint(f"role IN ({_ROLES_SQL})", name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), unique=True)  # always lowercase
    password_hash: Mapped[str]  # argon2id, in the PHC string format
    role: Mapped[str]  # one of ROLES
    created_at: Mapped[datetime]  # UTC


class ApiToken(Base):
    """A login of one device. Only the token's SHA-256 is stored, so the database leaks no usable token."""

    __tablename__ = "api_token"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    device_name: Mapped[str]
    created_at: Mapped[datetime]  # UTC
    last_used_at: Mapped[datetime]  # UTC


class Setting(Base):
    """A server setting that the admin can change, e.g. the path template. Missing means the default."""

    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class FileMove(Base):
    """A file move in progress. Written before the file is moved and deleted in the same transaction that
    records the new path, so after a crash the server can tell where the file is (see services/storage)."""

    __tablename__ = "file_move"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("image.id", ondelete="CASCADE"))
    from_path: Mapped[str]  # relative to the library folder
    to_path: Mapped[str]  # relative to the library folder
    created_at: Mapped[datetime]  # UTC
