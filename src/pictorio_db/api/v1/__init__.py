# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""REST API version 1, served under /api/v1."""

from fastapi import APIRouter

from pictorio_db.api.v1 import admin, auth, images, jobs, namespaces, preferences, server, tags

router = APIRouter(prefix="/api/v1")
router.include_router(server.router)
router.include_router(auth.router)
router.include_router(images.router)
router.include_router(tags.router)
router.include_router(namespaces.router)
router.include_router(preferences.router)
router.include_router(jobs.router)
router.include_router(admin.router)
