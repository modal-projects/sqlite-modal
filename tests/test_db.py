"""Database entity tests — no HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import modal
import pytest

from sqlite_modal.database import Database


@pytest.fixture
def db(tmp_path: Path, volume: modal.Volume) -> Iterator[Database]:
    database = Database.from_path(tmp_path / "t.sqlite", volume)
    database.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    yield database
    database.close()


def test_query_execute_roundtrip(db: Database) -> None:
    db.execute("INSERT INTO t (v) VALUES (?)", ("a",))
    assert db.query("SELECT v FROM t") == [{"v": "a"}]


def test_batch_params_seq_and_query(db: Database) -> None:
    results = db.batch(
        [
            {
                "type": "execute",
                "sql": "INSERT INTO t (v) VALUES (?)",
                "params_seq": [["x"], ["y"]],
            },
            {"type": "query", "sql": "SELECT v FROM t ORDER BY id", "params": []},
        ]
    )
    exec_result = results[0]
    assert "rowcount" in exec_result
    assert exec_result["rowcount"] == 2
    assert results[1] == {"rows": [{"v": "x"}, {"v": "y"}]}


def test_batch_rejects_unknown_type(db: Database) -> None:
    bad_op: Any = {
        "type": "drop",
        "sql": "INSERT INTO t (v) VALUES (?)",
        "params": ["x"],
    }
    with pytest.raises(ValueError, match="invalid batch op type"):
        db.batch([bad_op])


def test_batch_rolls_back_on_error(db: Database) -> None:
    with pytest.raises(Exception):
        db.batch(
            [
                {
                    "type": "execute",
                    "sql": "INSERT INTO t (v) VALUES (?)",
                    "params": ["ok"],
                },
                {
                    "type": "execute",
                    "sql": "INSERT INTO t (v) VALUES (?)",
                    "params": [None],
                },
            ]
        )
    assert db.query("SELECT COUNT(*) AS n FROM t") == [{"n": 0}]


def test_execute_rolls_back_partial_failure(db: Database) -> None:
    with pytest.raises(Exception):
        db.execute("INSERT INTO t (v) VALUES (?)", (None,))
    assert db.query("SELECT COUNT(*) AS n FROM t") == [{"n": 0}]
    db.execute("INSERT INTO t (v) VALUES (?)", ("ok",))
    assert db.query("SELECT v FROM t") == [{"v": "ok"}]


def test_flush_commits_volume(db: Database, volume: modal.Volume) -> None:
    db.flush()
    cast(MagicMock, volume.commit).assert_called_once()


def test_flush_releases_lock_before_volume_commit(
    db: Database, volume: modal.Volume, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = {"during_commit": False}

    def commit() -> None:
        held["during_commit"] = db._lock.locked()

    monkeypatch.setattr(volume, "commit", commit)
    db.flush()
    assert held["during_commit"] is False


def test_close_commit_true(db: Database, volume: modal.Volume) -> None:
    cast(MagicMock, volume.commit).reset_mock()
    path = Path(db.conn.execute("PRAGMA database_list").fetchone()[2])
    db.execute("INSERT INTO t (v) VALUES (?)", ("persist",))
    db.close(commit=True)
    cast(MagicMock, volume.commit).assert_called_once()
    reopened = Database.from_path(path, volume)
    try:
        assert reopened.query("SELECT v FROM t") == [{"v": "persist"}]
    finally:
        reopened.close()


def test_durability_after_flush(tmp_path: Path, volume: modal.Volume) -> None:
    path = tmp_path / "dur.sqlite"
    db = Database.from_path(path, volume)
    db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)")
    db.execute("INSERT INTO t (v) VALUES (?)", ("kept",))
    db.flush()
    db.close()
    again = Database.from_path(path, volume)
    try:
        assert again.query("SELECT v FROM t") == [{"v": "kept"}]
        wal = path.with_name(path.name + "-wal")
        assert (not wal.exists()) or wal.stat().st_size == 0
    finally:
        again.close()
