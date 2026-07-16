"""Database entity tests — no HTTP."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import modal
import pytest

from sqlite_modal.db import Database


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
