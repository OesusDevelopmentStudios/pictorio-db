# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 OesusDevelopmentStudios

import json
from pathlib import Path

import pytest

from pictorio_db.app import create_app
from pictorio_db.cli import main
from pictorio_db.config import Config


@pytest.fixture(autouse=True)
def isolated_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The commands never touch the user's real folders."""
    monkeypatch.setenv("PICTORIO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PICTORIO_LIBRARY_DIR", str(tmp_path / "library"))


def test_openapi_prints_the_api_schema(config: Config, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["openapi"])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == create_app(config).openapi()


def test_serve_refuses_invalid_settings(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PICTORIO_PORT", "not-a-port")

    exit_code = main(["serve"])

    assert exit_code == 1
    assert "PICTORIO_PORT" in capsys.readouterr().err


def test_serve_refuses_data_folder_it_cannot_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocking_file = tmp_path / "a-file"
    blocking_file.write_text("not a folder")
    monkeypatch.setenv("PICTORIO_DATA_DIR", str(blocking_file / "data"))

    exit_code = main(["serve"])

    assert exit_code == 1
    assert "cannot create the data folder" in capsys.readouterr().err


def test_serve_refuses_library_folder_it_cannot_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    blocking_file = tmp_path / "a-file"
    blocking_file.write_text("not a folder")
    monkeypatch.setenv("PICTORIO_LIBRARY_DIR", str(blocking_file / "library"))

    exit_code = main(["serve"])

    assert exit_code == 1
    assert "cannot create the library folder" in capsys.readouterr().err
