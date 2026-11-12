# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/tags: autocomplete and browsing tags."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import CurrentAuthentication, TagsServiceDependency
from pictorio_db.utils.problems import problem_responses

router = APIRouter(prefix="/tags", tags=["tags"])


class TagWithCount(BaseModel):
    tag: str = Field(examples=["author:sample_artist"])
    image_count: int = Field(description="All images with this tag, also ones the user cannot see")


class TagList(BaseModel):
    items: list[TagWithCount]


@router.get("", summary="Tags starting with a prefix, most used first", responses=problem_responses(401, 422))
def list_tags(
    _user: CurrentAuthentication,
    tags: TagsServiceDependency,
    prefix: Annotated[str, Query(max_length=200, description="May include a namespace: author:pol")] = "",
    namespace: Annotated[str | None, Query(max_length=100, description="Only this namespace")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TagList:
    matches = tags.autocomplete(prefix, namespace, limit)
    return TagList(items=[TagWithCount(tag=str(match.tag), image_count=match.image_count) for match in matches])
