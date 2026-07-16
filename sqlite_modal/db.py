"""SQLite database entity — path + ``modal.Volume`` persistence."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, NotRequired, Self, TypeAlias, TypedDict

import modal

SqlParam: TypeAlias = str | int | float | bool | None
SqlParams: TypeAlias = Sequence[SqlParam]
Row: TypeAlias = dict[str, SqlParam]

VOLUME_MOUNT = Path("/data")
DEFAULT_DB_PATH = VOLUME_MOUNT / "db.sqlite"


class ExecuteResult(TypedDict):
    """Result of a non-row-returning statement."""

    rowcount: int
    lastrowid: int


class BatchOp(TypedDict):
    """One step in ``Database.batch`` / ``Sqlite.batch``."""

    type: Literal["query", "execute"]
    sql: str
    params: NotRequired[list[SqlParam]]
    params_seq: NotRequired[list[list[SqlParam]]]


class SqlRequest(TypedDict):
    """Wire body for ``/v1/query`` and ``/v1/execute``."""

    sql: str
    params: list[SqlParam]


class BatchRequest(TypedDict):
    """Wire body for ``/v1/batch``."""

    ops: list[BatchOp]


class Database:
    """Local sqlite3 connection with durable storage via ``modal.Volume``."""

    def __init__(self, conn: sqlite3.Connection, volume: modal.Volume) -> None:
        self.conn = conn
        self.volume = volume
        self._lock = threading.Lock()

    @classmethod
    def from_path(cls, path: Path, volume: modal.Volume) -> Self:
        """Open SQLite at ``path`` on ``volume`` (creates the file if absent)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit: writes use explicit BEGIN/COMMIT; reads never leave a txn open.
        conn = sqlite3.connect(
            str(path),
            timeout=5.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return cls(conn, volume)

    def query(self, sql: str, params: SqlParams = ()) -> list[Row]:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            return [dict(row) for row in cur.fetchall()]

    def execute(self, sql: str, params: SqlParams = ()) -> ExecuteResult:
        with self._lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                cur = self.conn.execute(sql, tuple(params))
                result: ExecuteResult = {
                    "rowcount": cur.rowcount,
                    "lastrowid": int(cur.lastrowid or 0),
                }
                self.conn.execute("COMMIT")
                return result
            except Exception:
                self._rollback()
                raise

    def executemany(self, sql: str, params_seq: Sequence[SqlParams]) -> ExecuteResult:
        with self._lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                cur = self.conn.executemany(sql, [tuple(row) for row in params_seq])
                result: ExecuteResult = {
                    "rowcount": cur.rowcount,
                    "lastrowid": int(cur.lastrowid or 0),
                }
                self.conn.execute("COMMIT")
                return result
            except Exception:
                self._rollback()
                raise

    def batch(
        self, ops: Sequence[BatchOp]
    ) -> list[ExecuteResult | dict[str, list[Row]]]:
        """Run ops in one transaction (commit once; rollback on error)."""
        with self._lock:
            results: list[ExecuteResult | dict[str, list[Row]]] = []
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                for op in ops:
                    if op["type"] == "query":
                        cur = self.conn.execute(
                            op["sql"], tuple(op.get("params", ()))
                        )
                        results.append(
                            {"rows": [dict(row) for row in cur.fetchall()]}
                        )
                        continue

                    if "params_seq" in op:
                        cur = self.conn.executemany(
                            op["sql"], [tuple(r) for r in op["params_seq"]]
                        )
                    else:
                        cur = self.conn.execute(
                            op["sql"], tuple(op.get("params", ()))
                        )
                    results.append(
                        {
                            "rowcount": cur.rowcount,
                            "lastrowid": int(cur.lastrowid or 0),
                        }
                    )
                self.conn.execute("COMMIT")
            except Exception:
                self._rollback()
                raise
            return results

    def _rollback(self) -> None:
        try:
            self.conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def flush(self) -> None:
        """Checkpoint WAL and ``volume.commit`` (sync durability barrier)."""
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            self.volume.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            self.conn.close()
