# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""REST API version 1, served under /api/v1."""

from fastapi import APIRouter

from pictorio_db.api.v1 import auth, server

router = APIRouter(prefix="/api/v1")
router.include_router(server.router)
router.include_router(auth.router)
