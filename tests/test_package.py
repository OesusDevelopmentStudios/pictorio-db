# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import tomllib
from pathlib import Path

import pictorio_db


def test_version_matches_pyproject() -> None:
    pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    assert pictorio_db.__version__ == pyproject["project"]["version"]
