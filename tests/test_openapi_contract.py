# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

"""The API schema is committed as docs/openapi.json, so every API change shows up in review."""

import json
from pathlib import Path

from pictorio_db.app import create_app

SCHEMA_PATH = Path(__file__).parent.parent / "docs" / "openapi.json"


def test_api_matches_committed_schema() -> None:
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert create_app().openapi() == committed_schema, (
        "The API differs from docs/openapi.json. If the change is intended, update the file with:\n"
        "    pictorio-db openapi > docs/openapi.json"
    )
