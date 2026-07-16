"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import modal
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite"


@pytest.fixture
def volume() -> modal.Volume:
    vol = MagicMock()
    vol.commit = MagicMock()
    return cast(modal.Volume, vol)


@pytest.fixture
def api_client(
    temp_db_path: Path,
    volume: modal.Volume,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("SQLITE_MODAL_NAME", "test-db")

    from sqlite_modal import api as api_mod

    def fake_from_name(name: str) -> modal.Volume:
        return volume

    monkeypatch.setattr(api_mod.modal.Volume, "from_name", fake_from_name)
    monkeypatch.setattr(api_mod, "DEFAULT_DB_PATH", temp_db_path)

    with TestClient(api_mod.app) as client:
        yield client
