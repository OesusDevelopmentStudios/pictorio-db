# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Receives an image upload (multipart/form-data with the parts `file` and `metadata`) as it streams in.
FastAPI's own form handling would first write the whole upload to a temporary file without a size limit,
so a huge upload could fill the disk before it is refused."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from fastapi import Request
from python_multipart.multipart import MultipartParser, parse_options_header

from pictorio_db.utils.problems import Problem

FILE_PART = "file"
METADATA_PART = "metadata"
METADATA_MAX_BYTES = 64 * 1024
_MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and part headers on top of the file and the metadata


@dataclass
class _UploadState:
    """What the parser has seen so far, filled in by its callbacks."""

    target: Path
    max_file_bytes: int
    header_field: bytearray = field(default_factory=bytearray)
    header_value: bytearray = field(default_factory=bytearray)
    content_disposition: bytes = b""
    current_part: str | None = None
    file: BinaryIO | None = None
    file_bytes: int = 0
    seen_parts: set[str] = field(default_factory=set)
    metadata: bytearray = field(default_factory=bytearray)


async def receive_upload(request: Request, target: Path, max_file_bytes: int) -> bytes:
    """Writes the `file` part to `target` and returns the `metadata` part. On any error `target` is
    deleted; raises 413 file_too_large or 422 validation_error."""
    boundary = _boundary(request)
    _refuse_announced_size(request, max_file_bytes)
    state = _UploadState(target, max_file_bytes)
    parser = MultipartParser(boundary, _callbacks(state))
    try:
        async for chunk in request.stream():
            parser.write(chunk)

        parser.finalize()
        _check_both_parts_arrived(state)
    except BaseException:
        _close_file(state)
        target.unlink(missing_ok=True)
        raise

    _close_file(state)
    return bytes(state.metadata)


def _boundary(request: Request) -> bytes:
    content_type, options = parse_options_header(request.headers.get("content-type"))
    if content_type != b"multipart/form-data" or b"boundary" not in options:
        raise _invalid("body", "Send multipart/form-data with the parts 'file' and 'metadata'.")

    return options[b"boundary"]


def _refuse_announced_size(request: Request, max_file_bytes: int) -> None:
    """Refuses at once, before reading anything, if the client says the upload is too large."""
    content_length = request.headers.get("content-length", "")
    largest_acceptable = max_file_bytes + METADATA_MAX_BYTES + _MULTIPART_OVERHEAD_BYTES
    if content_length.isdigit() and int(content_length) > largest_acceptable:
        raise file_too_large(max_file_bytes)


def _callbacks(state: _UploadState) -> dict[str, object]:
    def on_part_begin() -> None:
        state.content_disposition = b""

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state.header_field += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state.header_value += data[start:end]

    def on_header_end() -> None:
        if bytes(state.header_field).lower() == b"content-disposition":
            state.content_disposition = bytes(state.header_value)

        state.header_field.clear()
        state.header_value.clear()

    def on_headers_finished() -> None:
        _disposition, options = parse_options_header(state.content_disposition)
        part_name = options.get(b"name", b"").decode("utf-8", errors="replace")
        if part_name in state.seen_parts:
            raise _invalid(part_name, "This part was sent twice.")

        state.seen_parts.add(part_name)
        state.current_part = part_name
        if part_name == FILE_PART:
            state.file = state.target.open("wb")

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if state.current_part == FILE_PART and state.file is not None:
            state.file_bytes += end - start
            if state.file_bytes > state.max_file_bytes:
                raise file_too_large(state.max_file_bytes)

            state.file.write(data[start:end])
        elif state.current_part == METADATA_PART:
            state.metadata += data[start:end]
            if len(state.metadata) > METADATA_MAX_BYTES:
                raise _invalid(METADATA_PART, f"At most {METADATA_MAX_BYTES} bytes.")

    def on_part_end() -> None:
        if state.current_part == FILE_PART:
            _close_file(state)

        state.current_part = None

    return {
        "on_part_begin": on_part_begin,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
    }


def _check_both_parts_arrived(state: _UploadState) -> None:
    for part_name in (FILE_PART, METADATA_PART):
        if part_name not in state.seen_parts:
            raise _invalid(part_name, "This part is missing.")


def _close_file(state: _UploadState) -> None:
    if state.file is not None:
        state.file.close()
        state.file = None


def file_too_large(limit_bytes: int) -> Problem:
    return Problem(
        413,
        "file_too_large",
        "File too large",
        f"The server accepts files of at most {limit_bytes} bytes.",
        limit_bytes=limit_bytes,
    )


def _invalid(field_name: str, message: str) -> Problem:
    return Problem(
        422,
        "validation_error",
        "Invalid request",
        "The request body or parameters are invalid.",
        errors=[{"field": field_name, "message": message}],
    )
