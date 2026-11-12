# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/images: uploading images, and reading them back with their files and thumbnails."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from pictorio_db.api.v1._upload_receiver import METADATA_PART, receive_upload
from pictorio_db.api.v1.dependencies import (
    CurrentAuthentication,
    ImagesServiceDependency,
    ImporterServiceDependency,
    SearchServiceDependency,
    StorageServiceDependency,
    ThumbnailsServiceDependency,
)
from pictorio_db.services.images import ImageRecord
from pictorio_db.services.importer import UploadMetadata
from pictorio_db.services.search import DEFAULT_LIMIT, MAX_LIMIT, Order, SearchRequest, Sort
from pictorio_db.services.thumbnails import THUMBNAIL_SIZES
from pictorio_db.utils.problems import Problem, problem_responses
from pictorio_db.utils.time import as_utc

router = APIRouter(prefix="/images", tags=["images"])

# A thumbnail never changes for a given SHA-256, so clients may keep it for good.
THUMBNAIL_CACHE_CONTROL = "private, max-age=31536000, immutable"


class ImageLinks(BaseModel):
    self: str
    file: str
    thumbnail: str


class ImageObject(BaseModel):
    id: int
    sha256: str
    original_filename: str
    storage_path: str = Field(description="Relative to the library folder")
    mime_type: str
    width: int = Field(description="As the image is shown, after its EXIF orientation")
    height: int
    file_size: int
    taken_at: datetime = Field(description="Local wall-clock time, without a time zone")
    taken_at_source: Literal["exif", "file_mtime", "import_time"]
    imported_at: datetime
    updated_at: datetime
    tags: list[str] = Field(
        description="Sorted by namespace, then name", examples=[["category:photo", "general:summer"]]
    )
    links: ImageLinks


class ImageList(BaseModel):
    items: list[ImageObject]
    next_cursor: str | None = Field(description="Pass as `cursor` for the next page; null on the last page")
    effective_query: str = Field(description="The query with the hidden-by-default filters that were added")


class UploadMetadataModel(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255, examples=["IMG_2041.jpg"])
    file_mtime: datetime | None = Field(default=None, description="The original file's modification time")
    client_sha256: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
    tags: list[str] = Field(default=[], max_length=200, examples=[["category:photo", "summer"]])


_UPLOAD_REQUEST_BODY = {
    "required": True,
    "content": {
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["file", "metadata"],
                "properties": {
                    "file": {"type": "string", "format": "binary", "description": "The image"},
                    "metadata": {
                        "type": "string",
                        "description": "JSON: original_filename, file_mtime?, client_sha256?, tags?",
                        "example": '{"original_filename": "IMG_2041.jpg", "tags": ["category:photo", "summer"]}',
                    },
                },
            }
        }
    },
}


@router.get("", summary="Search and list images", responses=problem_responses(400, 401, 422))
def search_images(
    _user: CurrentAuthentication,
    search: SearchServiceDependency,
    images: ImagesServiceDependency,
    q: Annotated[str, Query(max_length=2000, description="Search query, e.g. category:artwork -rating:nsfw")] = "",
    sort: Sort = Sort.TAKEN_AT,
    order: Annotated[Order, Query(description="Ignored for sort=random")] = Order.DESC,
    seed: Annotated[int | None, Query(description="Required for sort=random: same seed, same order")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=500, description="next_cursor of the previous page")] = None,
    apply_hidden_filters: Annotated[bool, Query(description="false skips your hidden-by-default filters")] = True,
) -> ImageList:
    request = SearchRequest(query=q, sort=sort, order=order, seed=seed, limit=limit, cursor=cursor)
    page = search.search(request)
    return ImageList(
        items=[_image_object(record) for record in images.get_images(page.image_ids)],
        next_cursor=page.next_cursor,
        effective_query=page.effective_query,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload one image",
    responses=problem_responses(401, 409, 413, 415, 422),
    openapi_extra={"requestBody": _UPLOAD_REQUEST_BODY},
)
async def upload_image(
    request: Request,
    response: Response,
    authentication: CurrentAuthentication,
    importer: ImporterServiceDependency,
) -> ImageObject:
    incoming = importer.new_incoming_path()
    metadata_json = await receive_upload(request, incoming, importer.max_upload_bytes())
    try:
        metadata = _parse_metadata(metadata_json)
    except Problem:
        incoming.unlink(missing_ok=True)
        raise

    # Hashing and thumbnails take a while; the server keeps answering other requests meanwhile.
    record = await run_in_threadpool(importer.import_image, incoming, metadata, authentication.user.id)
    response.headers["Location"] = f"/api/v1/images/{record.id}"
    return _image_object(record)


@router.get("/{image_id}", summary="One image", responses=problem_responses(401, 404, 422))
def get_image(image_id: int, _user: CurrentAuthentication, images: ImagesServiceDependency) -> ImageObject:
    return _image_object(images.get_image(image_id))


@router.get(
    "/{image_id}/file",
    summary="The original image file; supports Range and If-None-Match",
    response_class=FileResponse,
    responses={200: {"content": {"image/*": {}}}, 304: {"description": "Not modified"}, **problem_responses(401, 404)},
)
def get_image_file(
    image_id: int,
    request: Request,
    _user: CurrentAuthentication,
    images: ImagesServiceDependency,
    storage: StorageServiceDependency,
) -> Response:
    record = images.get_image(image_id)
    etag = f'"{record.sha256}"'
    if _client_has(request, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return FileResponse(
        storage.absolute_path(record.storage_path),
        media_type=record.mime_type,
        filename=record.original_filename,
        content_disposition_type="inline",
        headers={"ETag": etag},
    )


@router.get(
    "/{image_id}/thumbnail",
    summary="A WebP thumbnail; the longest side is at most `size` pixels",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/webp": {}}},
        304: {"description": "Not modified"},
        **problem_responses(401, 404, 422),
    },
)
def get_image_thumbnail(
    image_id: int,
    request: Request,
    _user: CurrentAuthentication,
    images: ImagesServiceDependency,
    storage: StorageServiceDependency,
    thumbnails: ThumbnailsServiceDependency,
    size: Annotated[int, Query(json_schema_extra={"enum": list(THUMBNAIL_SIZES)})] = 256,
) -> Response:
    if size not in THUMBNAIL_SIZES:  # query values arrive as text, so a Literal type would refuse every size
        raise Problem(
            422,
            "validation_error",
            "Invalid request",
            "The request body or parameters are invalid.",
            errors=[{"field": "query.size", "message": f"One of {list(THUMBNAIL_SIZES)}"}],
        )

    record = images.get_image(image_id)
    etag = f'"{record.sha256}-{size}"'
    headers = {"ETag": etag, "Cache-Control": THUMBNAIL_CACHE_CONTROL}
    if _client_has(request, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    thumbnail = thumbnails.thumbnail_path(record.sha256, size)
    if not thumbnail.exists():  # e.g. the thumbnail folder was cleared: make them again
        thumbnails.create_thumbnails(storage.absolute_path(record.storage_path), record.sha256)

    return FileResponse(thumbnail, media_type="image/webp", headers=headers)


def _parse_metadata(metadata_json: bytes) -> UploadMetadata:
    try:
        model = UploadMetadataModel.model_validate_json(metadata_json)
    except ValidationError as error:
        raise Problem(
            422,
            "validation_error",
            "Invalid request",
            "The request body or parameters are invalid.",
            errors=[
                {"field": ".".join([METADATA_PART, *(str(part) for part in issue["loc"])]), "message": issue["msg"]}
                for issue in error.errors()
            ],
        ) from None

    return UploadMetadata(
        original_filename=model.original_filename,
        file_mtime=model.file_mtime,
        client_sha256=model.client_sha256,
        tags=tuple(model.tags),
    )


def _client_has(request: Request, etag: str) -> bool:
    """If-None-Match: the client already has this version, so 304 Not Modified is enough."""
    if_none_match = request.headers.get("if-none-match", "")
    return etag in (tag.strip() for tag in if_none_match.split(",")) or if_none_match.strip() == "*"


def _image_object(record: ImageRecord) -> ImageObject:
    base = f"/api/v1/images/{record.id}"
    return ImageObject(
        id=record.id,
        sha256=record.sha256,
        original_filename=record.original_filename,
        storage_path=record.storage_path,
        mime_type=record.mime_type,
        width=record.width,
        height=record.height,
        file_size=record.file_size,
        taken_at=record.taken_at,
        taken_at_source=record.taken_at_source,  # type: ignore[arg-type]
        imported_at=as_utc(record.imported_at),
        updated_at=as_utc(record.updated_at),
        tags=[str(tag) for tag in record.tags],
        links=ImageLinks(self=base, file=f"{base}/file", thumbnail=f"{base}/thumbnail"),
    )
