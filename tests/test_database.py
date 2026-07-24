"""Unit tests for Sqlite.from_name / connect."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sqlite_modal import InvalidNameError, MissingError, Sqlite
from sqlite_modal import database as database_mod
from sqlite_modal.turso import APP_PREFIX, REMOTE_NAME


def test_app_name_property() -> None:
    db = Sqlite("orders")
    assert db.app_name == f"{APP_PREFIX}-orders"


def test_from_name_rejects_invalid() -> None:
    with pytest.raises(InvalidNameError):
        Sqlite.from_name("bad-name!", create_if_missing=True)
    with pytest.raises(InvalidNameError):
        Sqlite.from_name("1orders", create_if_missing=True)


def test_create_options_requires_create_if_missing() -> None:
    with pytest.raises(ValueError, match="create_options requires"):
        Sqlite.from_name("orders", create_options={"max_containers": 1})


def test_from_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Sqlite, "exists", lambda self: False)
    with pytest.raises(MissingError):
        Sqlite.from_name("orders")


def test_from_name_create_if_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed: dict[str, object] = {}

    monkeypatch.setattr(
        database_mod.modal.Volume,
        "from_name",
        lambda *a, **k: MagicMock(),
    )

    def fake_deploy(name: str, **kwargs: object) -> MagicMock:
        deployed["name"] = name
        deployed["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr(database_mod.RemoteApp, "deploy", fake_deploy)

    db = Sqlite.from_name(
        "orders",
        create_if_missing=True,
        create_options={"max_containers": 1, "compute_region": "uk"},
    )
    assert db.name == "orders"
    assert deployed["name"] == "orders"
    assert deployed["kwargs"] == {
        "create_options": {
            "max_containers": 1,
            "compute_region": "uk",
        },
        "environment_name": None,
        "client": None,
    }


def test_connect_rejects_empty_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Sqlite, "exists", lambda self: True)
    db = Sqlite.from_name("orders")
    with pytest.raises(ValueError, match="non-empty"):
        db.connect("")


def test_remote_url_is_bare(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Sqlite, "exists", lambda self: True)
    server = MagicMock()
    server.get_url.return_value = "https://tunnel.example/"
    seen: dict[str, object] = {}

    def fake_from_name(app: str, name: str, **kwargs: object) -> MagicMock:
        seen["app"] = app
        seen["name"] = name
        return server

    monkeypatch.setattr(database_mod.modal.Server, "from_name", fake_from_name)

    db = Sqlite.from_name("orders")
    assert db.remote_url == "https://tunnel.example"
    assert "?" not in db.remote_url
    assert seen["app"] == f"{APP_PREFIX}-orders"
    assert seen["name"] == REMOTE_NAME
    assert db.remote_url == "https://tunnel.example"
    server.get_url.assert_called_once()


def test_connect_uses_remote_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Sqlite, "exists", lambda self: True)
    fake_conn = MagicMock()
    server = MagicMock()
    server.get_url.return_value = "https://tunnel.example"
    seen: dict[str, str | None] = {}

    def fake_connect(path: str, remote_url: str | None = None) -> MagicMock:
        seen["path"] = path
        seen["remote_url"] = remote_url
        return fake_conn

    monkeypatch.setattr(
        database_mod.modal.Server,
        "from_name",
        lambda *a, **k: server,
    )
    monkeypatch.setattr(database_mod, "connect", fake_connect)

    db = Sqlite.from_name("orders")
    assert db.connect(tmp_path / "local.db") is fake_conn
    assert seen["remote_url"] == "https://tunnel.example"


def test_remote_url_requires_create(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Sqlite, "exists", lambda self: True)
    server = MagicMock()
    server.get_url.return_value = None
    monkeypatch.setattr(
        database_mod.modal.Server,
        "from_name",
        lambda *a, **k: server,
    )

    with pytest.raises(RuntimeError, match="create_if_missing=True"):
        _ = Sqlite.from_name("orders").remote_url
