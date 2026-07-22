"""Persistence — local sqlite3 + Volume durability."""

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


class ExecuteResult(TypedDict):
    rowcount: int
    lastrowid: int


class BatchOp(TypedDict):
    type: Literal["query", "execute"]
    sql: str
    params: NotRequired[list[SqlParam]]
    params_seq: NotRequired[list[list[SqlParam]]]


class Database:
    """Local sqlite3 connection with durable storage via ``modal.Volume``."""

    VOLUME_MOUNT = Path("/data")
    DEFAULT_PATH = VOLUME_MOUNT / "db.sqlite"
    MAX_BATCH_OPS = 1_000
    MAX_PARAMS_SEQ = 10_000

    def __init__(self, conn: sqlite3.Connection, volume: modal.Volume) -> None:
        self.conn = conn
        self.volume = volume
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def from_path(cls, path: Path, volume: modal.Volume) -> Self:
        path.parent.mkdir(parents=True, exist_ok=True)
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
        if len(ops) > self.MAX_BATCH_OPS:
            raise ValueError(f"batch exceeds {self.MAX_BATCH_OPS} ops")
        writes = any(op["type"] == "execute" for op in ops)
        with self._lock:
            results: list[ExecuteResult | dict[str, list[Row]]] = []
            try:
                self.conn.execute("BEGIN IMMEDIATE" if writes else "BEGIN")
                for op in ops:
                    op_type = op["type"]
                    if op_type == "query":
                        cur = self.conn.execute(
                            op["sql"], tuple(op.get("params", ()))
                        )
                        results.append(
                            {"rows": [dict(row) for row in cur.fetchall()]}
                        )
                        continue
                    if op_type != "execute":
                        raise ValueError(f"invalid batch op type {op_type!r}")
                    if "params_seq" in op:
                        params_seq = op["params_seq"]
                        if len(params_seq) > self.MAX_PARAMS_SEQ:
                            raise ValueError(
                                f"params_seq exceeds {self.MAX_PARAMS_SEQ} rows"
                            )
                        cur = self.conn.executemany(
                            op["sql"], [tuple(r) for r in params_seq]
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
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        # Commit outside the SQL lock so other requests are not blocked on Volume I/O.
        self.volume.commit()

    def close(self, *, commit: bool = False) -> None:
        with self._lock:
            if self._closed:
                return
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                self.conn.close()
                self._closed = True
        if commit:
            self.volume.commit()
