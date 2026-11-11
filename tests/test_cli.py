# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import json

import pytest

from pictorio_db.app import create_app
from pictorio_db.cli import main


def test_openapi_prints_the_api_schema(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["openapi"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == create_app().openapi()


def test_serve_refuses_invalid_settings(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PICTORIO_PORT", "not-a-port")

    exit_code = main(["serve"])

    assert exit_code == 1
    assert "PICTORIO_PORT" in capsys.readouterr().err
