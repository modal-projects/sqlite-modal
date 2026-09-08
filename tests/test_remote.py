"""Unit tests for SyncServer / ServerStore."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from sqlite_modal.remote import CreateOptions, RemoteApp, ServerStore, SyncServer
from sqlite_modal import remote as remote_mod
from sqlite_modal.turso import volume_name


def test_deploy_rejects_max_containers_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        remote_mod.modal.Volume, "from_name", lambda *a, **k: MagicMock()
    )
    with pytest.raises(ValueError, match="max_containers is fixed at 1"):
        RemoteApp.deploy(
            "orders",
            create_options=cast(CreateOptions, {"max_containers": 4}),
        )


def test_deploy_pins_single_sync_server(monkeypatch: pytest.MonkeyPatch) -> None:
    app = MagicMock()

    def fake_app(name: str) -> MagicMock:
        assert name == "sqlite-modal-orders"
        return app

    monkeypatch.setattr(
        remote_mod.modal.Volume, "from_name", lambda *a, **k: MagicMock()
    )
    monkeypatch.setattr(remote_mod.modal, "App", fake_app)
    monkeypatch.setattr(remote_mod.modal, "enable_output", MagicMock())

    RemoteApp.deploy("orders", create_options={"compute_region": "uk"})
    assert app.server.call_args.kwargs["max_containers"] == 1
    app.deploy.assert_called_once()


def test_volume_name_is_per_db() -> None:
    assert volume_name("orders") == "sqlite-modal-orders-data"
    assert volume_name("orders") != volume_name("notes")


def test_sync_server_is_module_level() -> None:
    assert SyncServer.__module__ == "sqlite_modal.remote"
    assert SyncServer.__name__ == "SyncServer"


def test_server_store_restore(tmp_path: Path) -> None:
    cold = tmp_path / "cold"
    hot = tmp_path / "hot" / "server.db"
    cold.mkdir()
    (cold / "server.db").write_bytes(b"main")
    (cold / "server.db-wal").write_bytes(b"wal")

    ServerStore(hot, cold).restore()

    assert (tmp_path / "hot" / "server.db").read_bytes() == b"main"
    assert (tmp_path / "hot" / "server.db-wal").read_bytes() == b"wal"


def test_server_store_restore_noop_without_cold(tmp_path: Path) -> None:
    hot = tmp_path / "hot" / "server.db"
    ServerStore(hot, tmp_path / "missing").restore()
    assert not hot.exists()


def test_server_store_save_clears_stale(tmp_path: Path) -> None:
    cold = tmp_path / "cold"
    hot_dir = tmp_path / "hot"
    hot = hot_dir / "server.db"
    cold.mkdir()
    hot_dir.mkdir()
    (cold / "server.db").write_bytes(b"old")
    (cold / "server.db-shm").write_bytes(b"stale")
    hot.write_bytes(b"new")
    (hot_dir / "server.db-wal").write_bytes(b"wal")

    ServerStore(hot, cold).save()

    assert (cold / "server.db").read_bytes() == b"new"
    assert (cold / "server.db-wal").read_bytes() == b"wal"
    assert not (cold / "server.db-shm").exists()


def test_server_store_save_noop_without_hot(tmp_path: Path) -> None:
    cold = tmp_path / "cold"
    cold.mkdir()
    (cold / "server.db").write_bytes(b"keep")
    ServerStore(tmp_path / "missing.db", cold).save()
    assert (cold / "server.db").read_bytes() == b"keep"
