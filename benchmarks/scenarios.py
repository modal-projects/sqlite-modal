"""Local read/write latency + throughput; sync/cold extras."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TypedDict

from turso.sync import ConnectionSync

from benchmarks.measure import LatencyMs, Samples
from sqlite_modal import Sqlite

NOTE_DDL = (
    "CREATE TABLE IF NOT EXISTS note (id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
)


class NoteTable:
    """Bench-only schema for the ``note`` table."""

    def reset(self, conn: ConnectionSync) -> None:
        conn.execute(NOTE_DDL)
        conn.execute("DELETE FROM note")
        conn.commit()


class LocalFiles:
    """Bench-only local path hygiene."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def clear(self) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        for p in parent.glob(f"{self.path.name}*"):
            p.unlink()


class LocalLatencyResult(TypedDict):
    scenario: str
    n: int
    read_ms: LatencyMs
    write_ms: LatencyMs


class LocalThroughputResult(TypedDict):
    scenario: str
    ops: int
    read_ops_per_s: float
    write_ops_per_s: float


class SyncLatencyResult(TypedDict):
    scenario: str
    n: int
    push_ms: LatencyMs
    pull_ms: LatencyMs


class ColdStartResult(TypedDict):
    scenario: str
    cold_first_ms: float
    warm_push_p50_ms: float
    warm_n: int
    scaledown_wait_s: float
    note: str


def local_latency(
    remote: Sqlite, local: Path, *, n: int, warmup: int
) -> LocalLatencyResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    reads = Samples()
    writes = Samples()
    with conn:
        notes.reset(conn)
        conn.push()
        for _ in range(warmup):
            conn.execute("SELECT 1").fetchall()
            conn.execute("INSERT INTO note (body) VALUES (?)", ("warmup",))
            conn.commit()

        for i in range(n):
            t0 = time.perf_counter()
            conn.execute("SELECT 1").fetchall()
            reads.add((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"lat-{i}",))
            conn.commit()
            writes.add((time.perf_counter() - t0) * 1000)

    return {
        "scenario": "local_latency",
        "n": n,
        "read_ms": reads.summary(),
        "write_ms": writes.summary(),
    }


def local_throughput(remote: Sqlite, local: Path, *, ops: int) -> LocalThroughputResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    with conn:
        notes.reset(conn)
        conn.push()

        t0 = time.perf_counter()
        for _ in range(ops):
            conn.execute("SELECT 1").fetchall()
        read_wall = time.perf_counter() - t0

        t0 = time.perf_counter()
        for i in range(ops):
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"thr-{i}",))
            conn.commit()
        write_wall = time.perf_counter() - t0

    return {
        "scenario": "local_throughput",
        "ops": ops,
        "read_ops_per_s": round(ops / read_wall, 1) if read_wall else 0.0,
        "write_ops_per_s": (round(ops / write_wall, 1) if write_wall else 0.0),
    }


def sync_latency(remote: Sqlite, local: Path, *, n: int) -> SyncLatencyResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    pushes = Samples()
    pulls = Samples()
    with conn:
        notes.reset(conn)
        conn.push()
        for i in range(n):
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"sync-{i}",))
            conn.commit()
            pushes.measure(conn.push)
            pulls.measure(conn.pull)

    return {
        "scenario": "sync_latency",
        "n": n,
        "push_ms": pushes.summary(),
        "pull_ms": pulls.summary(),
    }


def cold_start(
    remote: Sqlite,
    local: Path,
    *,
    scaledown_wait_s: float,
    warm_n: int = 20,
) -> ColdStartResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    with conn:
        notes.reset(conn)
        conn.push()

    time.sleep(scaledown_wait_s)

    files.clear()
    t0 = time.perf_counter()
    conn = remote.connect(local)
    with conn:
        notes.reset(conn)
        conn.push()
        cold_ms = (time.perf_counter() - t0) * 1000

        warm = Samples()
        for i in range(warm_n):
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"warm-{i}",))
            conn.commit()
            warm.measure(conn.push)

    return {
        "scenario": "cold_start",
        "cold_first_ms": round(cold_ms, 2),
        "warm_push_p50_ms": warm.summary()["p50"],
        "warm_n": warm_n,
        "scaledown_wait_s": scaledown_wait_s,
        "note": ("cold = connect wait (non-503) + schema + push after scale-to-zero"),
    }
