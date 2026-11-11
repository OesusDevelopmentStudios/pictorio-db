# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/server: lets a client check that a URL points to a compatible pictorio-db server."""

from fastapi import APIRouter
from pydantic import BaseModel

import pictorio_db

SERVER_NAME = "pictorio-db"
API_VERSION = 1

router = APIRouter(prefix="/server", tags=["server"])


class ServerInfo(BaseModel):
    name: str
    version: str
    api_version: int
    setup_required: bool  # no admin account exists yet; the client sends the user to /admin/setup


@router.get("/info", summary="Server name and versions (public)")
def server_info() -> ServerInfo:
    return ServerInfo(
        name=SERVER_NAME,
        version=pictorio_db.__version__,
        api_version=API_VERSION,
        setup_required=True,  # there are no user accounts yet
    )
