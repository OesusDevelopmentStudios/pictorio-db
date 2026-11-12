# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/namespaces: the part before ':' in a tag, e.g. 'author' in 'author:sample_artist'."""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pictorio_db.api.v1.dependencies import CurrentAdmin, CurrentAuthentication, TagsServiceDependency
from pictorio_db.services.tags import NamespaceInfo
from pictorio_db.utils.problems import problem_responses

router = APIRouter(prefix="/namespaces", tags=["namespaces"])


class NamespaceDetails(BaseModel):
    name: str
    single_value: bool = Field(description="An image has at most one tag in this namespace")
    is_builtin: bool = Field(description="Built-in namespaces cannot be deleted")
    in_path_template: bool = Field(description="Its tags form folder names in the library")


class NamespaceList(BaseModel):
    items: list[NamespaceDetails]


class NewNamespace(BaseModel):
    name: str = Field(max_length=100, examples=["weather"])  # the exact rule is checked by the service
    single_value: bool = False


@router.get("", summary="All namespaces", responses=problem_responses(401))
def list_namespaces(_user: CurrentAuthentication, tags: TagsServiceDependency) -> NamespaceList:
    return NamespaceList(items=[_namespace_details(namespace) for namespace in tags.list_namespaces()])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a namespace",
    responses=problem_responses(401, 403, 409, 422),
)
def create_namespace(
    new_namespace: NewNamespace, _admin: CurrentAdmin, tags: TagsServiceDependency
) -> NamespaceDetails:
    return _namespace_details(tags.create_namespace(new_namespace.name, new_namespace.single_value))


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused custom namespace",
    responses=problem_responses(401, 403, 404, 409),
)
def delete_namespace(name: str, _admin: CurrentAdmin, tags: TagsServiceDependency) -> None:
    tags.delete_namespace(name)


def _namespace_details(namespace: NamespaceInfo) -> NamespaceDetails:
    return NamespaceDetails(
        name=namespace.name,
        single_value=namespace.single_value,
        is_builtin=namespace.is_builtin,
        in_path_template=namespace.in_path_template,
    )
