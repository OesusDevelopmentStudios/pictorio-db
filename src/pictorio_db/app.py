# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Creates the web application: the REST API and its documentation."""

from fastapi import FastAPI

import pictorio_db
from pictorio_db.api import v1


def create_app() -> FastAPI:
    app = FastAPI(
        title="pictorio-db",
        version=pictorio_db.__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",  # interactive API documentation
        redoc_url=None,
    )
    app.include_router(v1.router)
    return app
