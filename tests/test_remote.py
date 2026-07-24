"""Unit tests for SyncServer / ServerStore."""

from __future__ import annotations

from pathlib import Path

from sqlite_modal.remote import ServerStore, SyncServer


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
