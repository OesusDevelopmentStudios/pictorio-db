# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Web admin pages under /admin. Like the REST routers they are thin: they call the same services."""

from fastapi import APIRouter

from pictorio_db.admin_web import setup

router = APIRouter(prefix="/admin", include_in_schema=False)  # web pages, not part of the REST API
router.include_router(setup.router)
