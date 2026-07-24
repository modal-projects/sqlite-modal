"""Adoption scenarios for Turso Sync remotes on Modal."""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class WarmLatencyResult(TypedDict):
    scenario: str
    n: int
    read_ms: LatencyMs
    write_ms: LatencyMs
    push_ms: LatencyMs
    pull_ms: LatencyMs


class ColdStartResult(TypedDict):
    scenario: str
    cold_first_ms: float
    warm_p50_ms: float
    warm_n: int
    scaledown_wait_s: float
    note: str


class ConcurrencyPoint(TypedDict):
    clients: int
    ops: int
    wall_s: float
    ops_per_s: float
    latency_ms: LatencyMs


class WriterConcurrencyResult(TypedDict):
    scenario: str
    points: list[ConcurrencyPoint]


class MultiDbParallelResult(TypedDict):
    scenario: str
    ops_per_db: int
    single_db_ops_per_s: float
    dual_combined_ops_per_s: float
    dual_a_ops_per_s: float
    dual_b_ops_per_s: float


class BatchSizePoint(TypedDict):
    batch_size: int
    wall_s: float
    rows_per_s: float


class BatchSizeSweepResult(TypedDict):
    scenario: str
    points: list[BatchSizePoint]


class PushCostResult(TypedDict):
    scenario: str
    n: int
    insert_ms: LatencyMs
    insert_and_push_ms: LatencyMs
    note: str


def warm_latency(
    remote: Sqlite, local: Path, *, n: int, warmup: int
) -> WarmLatencyResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    reads = Samples()
    writes = Samples()
    pushes = Samples()
    pulls = Samples()
    with conn:
        notes.reset(conn)
        conn.push()
        for _ in range(warmup):
            conn.execute("SELECT 1")
            conn.execute("INSERT INTO note (body) VALUES (?)", ("warmup",))
            conn.commit()
            conn.push()
            conn.pull()

        for i in range(n):
            t0 = time.perf_counter()
            conn.execute("SELECT 1").fetchall()
            reads.add((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"warm-{i}",))
            conn.commit()
            writes.add((time.perf_counter() - t0) * 1000)

            pushes.measure(conn.push)
            pulls.measure(conn.pull)

    return {
        "scenario": "warm_latency",
        "n": n,
        "read_ms": reads.summary(),
        "write_ms": writes.summary(),
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
    """Cold = connect + schema + push after scale-to-zero.

    Warm the remote once, idle past ``scaledown_window``, then measure the
    first successful sync path (``connect`` includes Server readiness).
    """
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
        "warm_p50_ms": warm.summary()["p50"],
        "warm_n": warm_n,
        "scaledown_wait_s": scaledown_wait_s,
        "note": (
            "cold includes Modal container bring-up (connect waits for "
            "non-503) + schema + push"
        ),
    }


def writer_concurrency(
    remote: Sqlite,
    workdir: Path,
    *,
    clients: Sequence[int] = (1, 4, 16),
    ops_per_client: int = 40,
) -> WriterConcurrencyResult:
    """Concurrent local writers each pushing to one remote (last-push-wins)."""
    workdir.mkdir(parents=True, exist_ok=True)
    notes = NoteTable()
    boot_path = workdir / "concurrency_boot.db"
    LocalFiles(boot_path).clear()
    conn = remote.connect(boot_path)
    with conn:
        notes.reset(conn)
        conn.push()

    points: list[ConcurrencyPoint] = []
    for n_clients in clients:

        def worker(client_id: int) -> list[float]:
            path = workdir / f"concurrency_c{client_id}.db"
            LocalFiles(path).clear()
            c = remote.connect(path)
            samples = Samples()
            with c:
                c.execute(NOTE_DDL)
                c.commit()
                c.pull()
                for j in range(ops_per_client):
                    t0 = time.perf_counter()
                    c.execute(
                        "INSERT INTO note (body) VALUES (?)",
                        (f"c{client_id}-{j}",),
                    )
                    c.commit()
                    c.push()
                    samples.add((time.perf_counter() - t0) * 1000)
            return samples.values

        t0 = time.perf_counter()
        latencies: list[float] = []
        with ThreadPoolExecutor(max_workers=n_clients) as pool:
            futures = [pool.submit(worker, i) for i in range(n_clients)]
            for fut in as_completed(futures):
                latencies.extend(fut.result())
        wall = time.perf_counter() - t0
        total_ops = n_clients * ops_per_client
        merged = Samples()
        for ms in latencies:
            merged.add(ms)
        points.append(
            {
                "clients": n_clients,
                "ops": total_ops,
                "wall_s": round(wall, 3),
                "ops_per_s": round(total_ops / wall, 1) if wall else 0.0,
                "latency_ms": merged.summary(),
            }
        )
    return {"scenario": "writer_concurrency", "points": points}


def multi_db_parallel(
    single: Sqlite,
    db_a: Sqlite,
    db_b: Sqlite,
    workdir: Path,
    *,
    ops_per_db: int = 80,
) -> MultiDbParallelResult:
    """Sequential push-writes on one DB vs two remotes in parallel."""
    workdir.mkdir(parents=True, exist_ok=True)
    notes = NoteTable()

    def write_many(remote: Sqlite, path: Path, prefix: str) -> float:
        LocalFiles(path).clear()
        conn = remote.connect(path)
        with conn:
            notes.reset(conn)
            conn.push()
            t1 = time.perf_counter()
            for i in range(ops_per_db):
                conn.execute(
                    "INSERT INTO note (body) VALUES (?)",
                    (f"{prefix}-{i}",),
                )
                conn.commit()
                conn.push()
            return time.perf_counter() - t1

    single_wall = write_many(single, workdir / "multi_single.db", "solo")
    single_rate = ops_per_db / single_wall if single_wall else 0.0

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(write_many, db_a, workdir / "multi_a.db", "a")
        fb = pool.submit(write_many, db_b, workdir / "multi_b.db", "b")
        wall_a = fa.result()
        wall_b = fb.result()
    parallel_wall = time.perf_counter() - t0
    combined_ops = ops_per_db * 2

    return {
        "scenario": "multi_db_parallel",
        "ops_per_db": ops_per_db,
        "single_db_ops_per_s": round(single_rate, 1),
        "dual_combined_ops_per_s": (
            round(combined_ops / parallel_wall, 1) if parallel_wall else 0.0
        ),
        "dual_a_ops_per_s": round(ops_per_db / wall_a, 1) if wall_a else 0.0,
        "dual_b_ops_per_s": round(ops_per_db / wall_b, 1) if wall_b else 0.0,
    }


def batch_size_sweep(
    remote: Sqlite,
    local: Path,
    *,
    sizes: tuple[int, ...] = (10, 100, 1000),
) -> BatchSizeSweepResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    points: list[BatchSizePoint] = []
    with conn:
        notes.reset(conn)
        conn.push()
        for size in sizes:
            conn.execute("DELETE FROM note")
            conn.commit()
            t0 = time.perf_counter()
            conn.executemany(
                "INSERT INTO note (body) VALUES (?)",
                [(f"sz-{size}-{i}",) for i in range(size)],
            )
            conn.commit()
            conn.push()
            wall = time.perf_counter() - t0
            points.append(
                {
                    "batch_size": size,
                    "wall_s": round(wall, 4),
                    "rows_per_s": round(size / wall, 1) if wall else 0.0,
                }
            )
    return {"scenario": "batch_size_sweep", "points": points}


def push_cost(remote: Sqlite, local: Path, *, n: int) -> PushCostResult:
    files = LocalFiles(local)
    notes = NoteTable()
    files.clear()
    conn = remote.connect(local)
    insert_only = Samples()
    insert_push = Samples()
    with conn:
        notes.reset(conn)
        conn.push()
        for i in range(n):
            t0 = time.perf_counter()
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"io-{i}",))
            conn.commit()
            insert_only.add((time.perf_counter() - t0) * 1000)

            t0 = time.perf_counter()
            conn.execute("INSERT INTO note (body) VALUES (?)", (f"ip-{i}",))
            conn.commit()
            conn.push()
            insert_push.add((time.perf_counter() - t0) * 1000)
    return {
        "scenario": "push_cost",
        "n": n,
        "insert_ms": insert_only.summary(),
        "insert_and_push_ms": insert_push.summary(),
        "note": "push syncs to tursodb; Volume durability is exit-only",
    }
