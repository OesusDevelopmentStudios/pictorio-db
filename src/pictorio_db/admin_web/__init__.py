# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Web admin pages under /admin. Like the REST routers they are thin: they call the same services."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from pictorio_db.admin_web import login, overview, setup
from pictorio_db.admin_web._session import install_page_handlers

router = APIRouter(prefix="/admin", include_in_schema=False)  # web pages, not part of the REST API
router.include_router(setup.router)
router.include_router(login.router)
router.add_api_route("", overview.overview, response_class=HTMLResponse)  # /admin itself: a router needs a path

__all__ = ["install_page_handlers", "router"]
