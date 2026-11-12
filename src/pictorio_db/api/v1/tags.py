# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/tags: autocomplete and browsing tags; renaming and deleting them for admins."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import (
    CurrentAdmin,
    CurrentRestrictions,
    TagAdminDependency,
    TagsServiceDependency,
)
from pictorio_db.services.tags import TagName
from pictorio_db.utils.problems import problem_responses

router = APIRouter(prefix="/tags", tags=["tags"])


class TagWithCount(BaseModel):
    tag: str = Field(examples=["author:sample_artist"])
    image_count: int = Field(description="All images with this tag, also ones the user cannot see")


class TagList(BaseModel):
    items: list[TagWithCount]


@router.get("", summary="Tags starting with a prefix, most used first", responses=problem_responses(401, 422))
def list_tags(
    restrictions: CurrentRestrictions,
    tags: TagsServiceDependency,
    prefix: Annotated[str, Query(max_length=200, description="May include a namespace: author:pol")] = "",
    namespace: Annotated[str | None, Query(max_length=100, description="Only this namespace")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TagList:
    is_hidden = restrictions.is_tag_hidden if restrictions.active else None  # restricted tags are never suggested
    matches = tags.autocomplete(prefix, namespace, limit, is_hidden)
    return TagList(items=[TagWithCount(tag=str(match.tag), image_count=match.image_count) for match in matches])


class TagRename(BaseModel):
    new_tag: str = Field(max_length=300, examples=["author:sample_artist"])


class RenamedTag(BaseModel):
    tag: str = Field(description="The new tag, normalized", examples=["author:sample_artist"])
    job_id: int | None = Field(description="The job that moves the affected files, if their folders change")


class DeletedTag(BaseModel):
    job_id: int | None = Field(description="The job that moves the affected files, if their folders change")


@router.patch(
    "/{namespace}/{name}",
    summary="Rename a tag, or merge it into an existing one, on every image",
    responses=problem_responses(401, 403, 404, 409, 422),
)
def rename_tag(
    namespace: str, name: str, rename: TagRename, admin: CurrentAdmin, tag_admin: TagAdminDependency
) -> RenamedTag:
    new_tag, job = tag_admin.rename_tag(TagName(namespace, name), rename.new_tag, admin.user.id)
    return RenamedTag(tag=str(new_tag), job_id=None if job is None else job.id)


@router.delete(
    "/{namespace}/{name}",
    summary="Remove a tag from every image and delete it",
    responses=problem_responses(401, 403, 404, 409),
)
def delete_tag(namespace: str, name: str, admin: CurrentAdmin, tag_admin: TagAdminDependency) -> DeletedTag:
    job = tag_admin.delete_tag(TagName(namespace, name), admin.user.id)
    return DeletedTag(job_id=None if job is None else job.id)
