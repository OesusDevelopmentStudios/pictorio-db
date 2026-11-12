# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""Creates the web application: the REST API and its documentation, on top of the database."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

import pictorio_db
from pictorio_db.api import v1
from pictorio_db.config import Config
from pictorio_db.db import DATABASE_FILE_NAME, open_database


def create_app(config: Config) -> FastAPI:
    """Creating the app touches no files; the database is opened when the server starts.
    config.data_dir must exist by then."""
    app = FastAPI(
        title="pictorio-db",
        version=pictorio_db.__version__,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",  # interactive API documentation
        redoc_url=None,
        lifespan=_lifespan(config),
    )
    app.include_router(v1.router)
    return app


def _lifespan(config: Config) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Creates the database on first start and upgrades its schema after an update.
        database = open_database(config.data_dir / DATABASE_FILE_NAME)
        app.state.database = database
        yield
        database.close()

    return lifespan
