# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import Select, and_, bindparam, delete, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pictorio_db.db import Database
from pictorio_db.db.models import Image, Namespace, Tag, image_tag
from pictorio_db.services.access import Restrictions
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagName, TagsService
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


# Checks one image's tags before and after a change, and its date; raises a Problem to cancel the whole change.
TagChangeCheck = Callable[[list[TagName], list[TagName], datetime], None]

_logger = logging.getLogger(__name__)


class ImagesService:
    """Image records and their tags. When a tag change affects an image's folder, its file is moved."""

    def __init__(self, database: Database, tags: TagsService, storage: StorageService) -> None:
        self._database = database
        self._tags = tags
        self._storage = storage

    def get_image(self, image_id: int) -> ImageRecord:
        with self._database.session() as session:
            image = session.get(Image, image_id)
            if image is None:
                raise Problem(404, "not_found", "Image not found")

            return _record(session, image)

    def get_visible_image(self, image_id: int, restrictions: Restrictions) -> ImageRecord:
        """404 not_found also for an image the user is restricted from: it behaves as if it did not exist."""
        if not self.is_visible(image_id, restrictions):
            raise Problem(404, "not_found", "Image not found")

        return self.get_image(image_id)

    def is_visible(self, image_id: int, restrictions: Restrictions) -> bool:
        with self._database.session() as session:
            statement = select(Image.id).where(Image.id == image_id, restrictions.visible_images_filter())
            return session.scalar(statement) is not None

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

    def change_tags(
        self, image_id: int, add_tags: list[str], remove_tags: list[str], restrictions: Restrictions
    ) -> ImageRecord:
        """Removes, then adds tags (unknown tags are created). In a single-value namespace an added tag replaces
        the image's current one. If its folder changes, the file is moved before this returns.
        Raises 404 not_found, 403 tag_restricted or 422 invalid_tag."""
        self.change_tags_of_many([image_id], add_tags, remove_tags, restrictions)
        return self.get_image(image_id)

    def change_tags_of_many(
        self, image_ids: list[int], add_tags: list[str], remove_tags: list[str], restrictions: Restrictions
    ) -> int:
        """The same change for several images, in one transaction: if anything fails, nothing changes. Files
        are moved after the commit. Images the user is restricted from count as unknown. Raises 404 not_found
        without saying which id, 403 tag_restricted if an image would become restricted, or 422 invalid_tag."""
        additions = self._tags.resolve_tags(add_tags)
        removals = {self._tags.parse_tag(text) for text in remove_tags}
        unique_ids = list(dict.fromkeys(image_ids))
        with self._database.session() as session:
            images = session.scalars(
                select(Image).where(Image.id.in_(unique_ids), restrictions.visible_images_filter())
            ).all()
            if len(images) != len(unique_ids):
                raise Problem(404, "not_found", "Image not found", "One of the images does not exist.")

            def check(_old_tags: list[TagName], new_tags: list[TagName], taken_at: datetime) -> None:
                restrictions.check_tags_allowed(new_tags, taken_at)

            changed_ids = self._change_tags(session, images, unique_ids, additions, removals, check)
            session.commit()

        self._move_files_to_layout(changed_ids)
        return len(unique_ids)

    def replace_tag(self, old_tag: TagName, new_tag: TagName | None, check: TagChangeCheck) -> list[int]:
        """For admins: every image with old_tag gets new_tag instead (a rename, or a merge if new_tag exists), or
        loses it if new_tag is None; then old_tag is deleted. In one transaction: if `check` raises, nothing
        changes. Files are not moved: returns the ids of the changed images, for a relayout. Raises 404 not_found."""
        with self._database.session() as session:
            old_tag_id = session.scalar(
                select(Tag.id)
                .join(Namespace, Tag.namespace_id == Namespace.id)
                .where(Namespace.name == old_tag.namespace, Tag.name == old_tag.name)
            )
            if old_tag_id is None:
                raise Problem(404, "not_found", "Tag not found")

            additions = [] if new_tag is None else [new_tag]
            _tag_ids(session, additions)  # the new tag exists afterwards, even if no image had the old one
            tagged_ids = select(image_tag.c.image_id).where(image_tag.c.tag_id == old_tag_id)
            images = session.scalars(select(Image).where(Image.id.in_(tagged_ids))).all()
            changed_ids = self._change_tags(session, images, tagged_ids, additions, {old_tag}, check)
            session.execute(delete(Tag).where(Tag.id == old_tag_id))
            session.commit()

        return changed_ids

    def all_image_ids(self) -> list[int]:
        with self._database.session() as session:
            return list(session.scalars(select(Image.id).order_by(Image.id)))

    def move_file_to_layout(self, image_id: int) -> bool:
        """Moves the image's file to where its tags and the path template place it. False if it was there.
        Raises 404 not_found, or OSError if moving fails; the file then stays where the database says."""
        record = self.get_image(image_id)
        current_path = PurePosixPath(record.storage_path)
        return self._storage.move_to_layout(record.id, current_path, record.tags, record.taken_at) != current_path

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

    def _change_tags(
        self,
        session: Session,
        images: Sequence[Image],
        image_ids: list[int] | Select[tuple[int]],
        additions: list[TagName],
        removals: set[TagName],
        check: TagChangeCheck,
    ) -> list[int]:
        """Removes, then adds tags; in a single-value namespace an added tag replaces the current one. Does not
        commit. Returns the ids of the images whose tags changed."""
        single_value = {namespace.name for namespace in self._tags.list_namespaces() if namespace.single_value}
        current_tags = _tags_of(session, image_ids)
        changes: list[_TagChange] = []
        for image in images:
            old_tags = current_tags.get(image.id, [])
            new_tags = _tags_after_change(old_tags, additions, removals, single_value)
            check(old_tags, new_tags, image.taken_at)
            removed = [tag for tag in old_tags if tag not in new_tags]
            change = _TagChange(image.id, removed, added=[tag for tag in new_tags if tag not in old_tags])
            if change.removed or change.added:
                changes.append(change)

        _save_tag_changes(session, changes)
        return [change.image_id for change in changes]

    def _move_files_to_layout(self, image_ids: list[int]) -> None:
        """After a tag change. A failed move leaves the file where the database says it is; it is logged, and
        the tag change stays."""
        for image_id in image_ids:
            try:
                self.move_file_to_layout(image_id)
            except OSError as error:
                _logger.error("Could not move the file of image %s after a tag change: %s", image_id, error)


def duplicate_image(sha256: str, existing_image_id: int | None) -> Problem:
    extra: dict[str, object] = {"sha256": sha256}
    if existing_image_id is not None:
        extra["existing_image_id"] = existing_image_id

    return Problem(
        409, "duplicate_image", "Image already exists", "An image with this SHA-256 is already in the library.",
        **extra,
    )


def _tags_after_change(
    current: list[TagName], additions: list[TagName], removals: set[TagName], single_value: set[str]
) -> list[TagName]:
    tags = [tag for tag in current if tag not in removals]
    for added in additions:
        if added.namespace in single_value:
            tags = [tag for tag in tags if tag.namespace != added.namespace]

        if added not in tags:
            tags.append(added)

    return tags


@dataclass(frozen=True)
class _TagChange:
    image_id: int
    removed: list[TagName]
    added: list[TagName]


def _save_tag_changes(session: Session, changes: list[_TagChange]) -> None:
    """In a few statements for all images, so that renaming a tag on thousands of images stays quick."""
    if not changes:
        return

    tags = list(dict.fromkeys(tag for change in changes for tag in [*change.removed, *change.added]))
    tag_ids = dict(zip(tags, _tag_ids(session, tags)))
    links = image_tag.c
    removed_links = [
        {"link_image_id": change.image_id, "link_tag_id": tag_ids[tag]} for change in changes for tag in change.removed
    ]
    if removed_links:
        is_link = and_(links.image_id == bindparam("link_image_id"), links.tag_id == bindparam("link_tag_id"))
        session.execute(delete(image_tag).where(is_link), removed_links)

    added_links = [{"image_id": change.image_id, "tag_id": tag_ids[tag]} for change in changes for tag in change.added]
    if added_links:
        session.execute(insert(image_tag), added_links)

    # The images table itself, not the Image class: an ORM update would check every loaded Image object.
    images = Image.__table__.c
    session.execute(
        update(Image.__table__).where(images.id == bindparam("changed_id")).values(updated_at=utc_now()),
        [{"changed_id": change.image_id} for change in changes],
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


def _tags_of(session: Session, image_ids: list[int] | Select[tuple[int]]) -> dict[int, list[TagName]]:
    """The tags of each image, sorted by namespace, then name. A query for the ids avoids SQLite's limit on the
    number of values in one statement."""
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
