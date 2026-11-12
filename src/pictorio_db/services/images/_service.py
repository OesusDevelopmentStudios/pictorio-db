# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pictorio_db.db import Database
from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.tags import TagName
from pictorio_db.utils.problems import Problem
from pictorio_db.utils.time import utc_now


@dataclass(frozen=True)
class NewImage:
    sha256: str
    storage_path: str  # relative to the library folder
    original_filename: str
    mime_type: str
    width: int
    height: int
    file_size: int
    taken_at: datetime  # local wall-clock time
    taken_at_source: str  # "exif", "file_mtime" or "import_time"
    taken_at_utc_offset_minutes: int | None
    imported_by_user_id: int | None


@dataclass(frozen=True)
class ImageRecord:
    id: int
    sha256: str
    storage_path: str
    original_filename: str
    mime_type: str
    width: int
    height: int
    file_size: int
    taken_at: datetime
    taken_at_source: str
    taken_at_utc_offset_minutes: int | None
    imported_at: datetime  # UTC
    updated_at: datetime  # UTC
    imported_by_user_id: int | None
    tags: list[TagName]  # sorted by namespace, then name


class ImagesService:
    """Image records and their tags."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def get_image(self, image_id: int) -> ImageRecord:
        with self._database.session() as session:
            image = session.get(Image, image_id)
            if image is None:
                raise Problem(404, "not_found", "Image not found")

            return _record(session, image)

    def get_images(self, image_ids: list[int]) -> list[ImageRecord]:
        """In the order of `image_ids`; ids that do not exist are left out. Tags are read in one query."""
        with self._database.session() as session:
            images = {image.id: image for image in session.scalars(select(Image).where(Image.id.in_(image_ids)))}
            tags = _tags_of(session, list(images))
            return [
                _record_with_tags(images[image_id], tags.get(image_id, []))
                for image_id in image_ids
                if image_id in images
            ]

    def find_id_by_sha256(self, sha256: str) -> int | None:
        with self._database.session() as session:
            return session.scalar(select(Image.id).where(Image.sha256 == sha256))

    def create_image(self, new_image: NewImage, tags: list[TagName]) -> ImageRecord:
        """The image, its new tags and their links in one transaction. Raises 409 duplicate_image if an
        image with the same SHA-256 exists, also when another upload was a moment faster."""
        now = utc_now()
        image = Image(**vars(new_image), imported_at=now, updated_at=now)
        with self._database.session() as session:
            session.add(image)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                existing_image_id = self.find_id_by_sha256(new_image.sha256)
                if existing_image_id is None:
                    raise  # not a duplicate image: the storage path is taken, a mistake of the caller

                raise duplicate_image(new_image.sha256, existing_image_id) from None

            for tag_id in _tag_ids(session, tags):
                session.execute(image_tag.insert().values(image_id=image.id, tag_id=tag_id))

            session.commit()
            return _record(session, image)


def duplicate_image(sha256: str, existing_image_id: int | None) -> Problem:
    extra: dict[str, object] = {"sha256": sha256}
    if existing_image_id is not None:
        extra["existing_image_id"] = existing_image_id

    return Problem(
        409, "duplicate_image", "Image already exists", "An image with this SHA-256 is already in the library.",
        **extra,
    )


def _tag_ids(session: Session, tags: list[TagName]) -> list[int]:
    """The ids of the tags, creating the ones that do not exist yet."""
    namespace_ids = {name: namespace_id for name, namespace_id in session.execute(select(Namespace.name, Namespace.id))}
    tag_ids = []
    for tag_name in dict.fromkeys(tags):  # each tag once, in the given order
        namespace_id = namespace_ids[tag_name.namespace]
        tag = session.scalars(select(Tag).where(Tag.namespace_id == namespace_id, Tag.name == tag_name.name)).first()
        if tag is None:
            tag = Tag(namespace_id=namespace_id, name=tag_name.name)
            session.add(tag)
            session.flush()

        tag_ids.append(tag.id)

    return tag_ids


def _record(session: Session, image: Image) -> ImageRecord:
    return _record_with_tags(image, _tags_of(session, [image.id]).get(image.id, []))


def _tags_of(session: Session, image_ids: list[int]) -> dict[int, list[TagName]]:
    """The tags of each image, sorted by namespace, then name."""
    tag_rows = session.execute(
        select(image_tag.c.image_id, Namespace.name, Tag.name)
        .join(Tag, Tag.namespace_id == Namespace.id)
        .join(image_tag, image_tag.c.tag_id == Tag.id)
        .where(image_tag.c.image_id.in_(image_ids))
        .order_by(Namespace.name, Tag.name)
    )
    tags: dict[int, list[TagName]] = {}
    for image_id, namespace, name in tag_rows:
        tags.setdefault(image_id, []).append(TagName(namespace, name))

    return tags


def _record_with_tags(image: Image, tags: list[TagName]) -> ImageRecord:
    return ImageRecord(
        id=image.id,
        sha256=image.sha256,
        storage_path=image.storage_path,
        original_filename=image.original_filename,
        mime_type=image.mime_type,
        width=image.width,
        height=image.height,
        file_size=image.file_size,
        taken_at=image.taken_at,
        taken_at_source=image.taken_at_source,
        taken_at_utc_offset_minutes=image.taken_at_utc_offset_minutes,
        imported_at=image.imported_at,
        updated_at=image.updated_at,
        imported_by_user_id=image.imported_by_user_id,
        tags=tags,
    )
