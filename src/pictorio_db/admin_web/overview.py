# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""/admin: the start page, with the state of the server at a glance."""

from fastapi import Request
from fastapi.responses import HTMLResponse

import pictorio_db
from pictorio_db.admin_web._session import AdminPage
from pictorio_db.admin_web._templates import templates

RECENT_JOBS = 5


def overview(request: Request, session: AdminPage) -> HTMLResponse:
    state = request.app.state
    context = {
        "session": session,
        "version": pictorio_db.__version__,
        "image_count": state.images.image_count(),
        "user_count": len(state.auth.list_users()),
        "settings": state.server_settings.current(),
        "recent_jobs": state.jobs.list_jobs(session.user)[:RECENT_JOBS],
    }
    return templates.TemplateResponse(request, "overview.html", context)
