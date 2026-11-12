# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Renaming, merging and deleting tags across the library, for admins."""

from datetime import datetime

from pictorio_db.services.access import AccessService
from pictorio_db.services.images import ImagesService, TagChangeCheck
from pictorio_db.services.jobs import JobInfo, Relayout
from pictorio_db.services.storage import StorageService
from pictorio_db.services.tags import TagName, TagsService
from pictorio_db.utils.problems import Problem


class TagAdmin:
    def __init__(
        self,
        tags: TagsService,
        images: ImagesService,
        access: AccessService,
        storage: StorageService,
        relayout: Relayout,
    ) -> None:
        self._tags = tags
        self._images = images
        self._access = access
        self._storage = storage
        self._relayout = relayout

    def rename_tag(self, old_tag: TagName, new_tag_text: str, user_id: int | None) -> tuple[TagName, JobInfo | None]:
        """Gives every image with old_tag the new tag instead; an existing new tag is merged with it. In a
        single-value namespace the new tag replaces the image's current one. Returns the new tag and the job
        that moves the affected files, if the path template uses either namespace. Raises 404 not_found,
        409 would_reveal_restricted_images or 422 invalid_tag."""
        [new_tag] = self._tags.resolve_tags([new_tag_text])
        if new_tag == old_tag:
            if not self._tags.tag_exists(old_tag):
                raise Problem(404, "not_found", "Tag not found")

            return new_tag, None

        changed_ids = self._images.replace_tag(old_tag, new_tag, self._keeps_restricted_images_hidden())
        return new_tag, self._relayout_if_needed(changed_ids, {old_tag.namespace, new_tag.namespace}, user_id)

    def delete_tag(self, tag: TagName, user_id: int | None) -> JobInfo | None:
        """Removes the tag from every image and deletes it. Returns the job that moves the affected files, if
        the path template uses its namespace. Raises 404 not_found or 409 would_reveal_restricted_images."""
        changed_ids = self._images.replace_tag(tag, None, self._keeps_restricted_images_hidden())
        return self._relayout_if_needed(changed_ids, {tag.namespace}, user_id)

    def _keeps_restricted_images_hidden(self) -> TagChangeCheck:
        """Restrictions name tags, so renaming or deleting rating:nsfw would show those images to restricted
        users. Such a change is refused until the admin changes the restrictions."""
        restricted_users = self._access.restricted_users()

        def check(old_tags: list[TagName], new_tags: list[TagName], taken_at: datetime) -> None:
            revealed_to = sorted(
                username
                for username, restrictions in restricted_users.items()
                if not restrictions.is_visible(old_tags, taken_at) and restrictions.is_visible(new_tags, taken_at)
            )
            if revealed_to:
                raise Problem(
                    409,
                    "would_reveal_restricted_images",
                    "Restricted images would become visible",
                    f"Images would become visible to users restricted from them: {', '.join(revealed_to)}. "
                    "Change their restricted tags first.",
                    users=revealed_to,
                )

        return check

    def _relayout_if_needed(self, changed_ids: list[int], namespaces: set[str], user_id: int | None) -> JobInfo | None:
        if not changed_ids or not namespaces & self._storage.path_template_namespaces():
            return None

        return self._relayout.start(user_id, changed_ids)


__all__ = ["TagAdmin"]
