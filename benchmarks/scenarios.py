"""Adoption-focused benchmark scenarios for sqlite_modal."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict

from sqlite_modal import Sqlite


class LatencyMs(TypedDict):
    p50: float
    p95: float
    mean: float


class WarmLatencyResult(TypedDict):
    scenario: str
    n: int
    read_ms: LatencyMs
    write_ms: LatencyMs


class ColdStartResult(TypedDict):
    scenario: str
    cold_first_ms: float
    warm_p50_ms: float
    warm_n: int
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


class FlushCostResult(TypedDict):
    scenario: str
    n: int
    insert_ms: LatencyMs
    insert_and_flush_ms: LatencyMs
    note: str


def percentile(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    xs = sorted(samples)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def latency_stats(samples: list[float]) -> LatencyMs:
    return {
        "p50": round(percentile(samples, 50), 2),
        "p95": round(percentile(samples, 95), 2),
        "mean": round(statistics.fmean(samples), 2) if samples else 0.0,
    }


def timed_ms(fn: Callable[[], object]) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


NOTE_DDL = (
    "CREATE TABLE IF NOT EXISTS note (id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
)


def ensure_schema(db: Sqlite) -> None:
    db.execute(NOTE_DDL)
    db.execute("DELETE FROM note")


def warm_latency(db: Sqlite, *, n: int, warmup: int) -> WarmLatencyResult:
    for _ in range(warmup):
        db.query("SELECT 1 AS ok")
        db.execute("INSERT INTO note (body) VALUES (?)", ("warmup",))

    reads: list[float] = []
    writes: list[float] = []
    for i in range(n):

        def do_read() -> None:
            db.query("SELECT 1 AS ok")

        def do_write(idx: int = i) -> None:
            db.execute("INSERT INTO note (body) VALUES (?)", (f"warm-{idx}",))

        reads.append(timed_ms(do_read))
        writes.append(timed_ms(do_write))
    return {
        "scenario": "warm_latency",
        "n": n,
        "read_ms": latency_stats(reads),
        "write_ms": latency_stats(writes),
    }


def cold_start(
    db: Sqlite,
    *,
    scaledown_wait_s: float,
    warm_n: int = 20,
) -> ColdStartResult:
    """Measure first SQL after idle vs warm p50.

    ``db`` must be attached with ``min_containers=0`` and a short
    ``scaledown_window``. Caller warms once, then waits for scale-down.
    """
    # Ensure schema exists and container is up, then let it scale to zero.
    ensure_schema(db)
    db.query("SELECT 1 AS ok")
    time.sleep(scaledown_wait_s)

    cold_ms = timed_ms(lambda: db.query("SELECT 1 AS ok"))

    warm_samples: list[float] = []
    for _ in range(warm_n):
        warm_samples.append(timed_ms(lambda: db.query("SELECT 1 AS ok")))

    return {
        "scenario": "cold_start",
        "cold_first_ms": round(cold_ms, 2),
        "warm_p50_ms": latency_stats(warm_samples)["p50"],
        "warm_n": warm_n,
        "note": (
            f"waited {scaledown_wait_s:.0f}s after last request for scale-to-zero"
        ),
    }


def writer_concurrency(
    db: Sqlite,
    *,
    clients: Sequence[int] = (1, 4, 16),
    ops_per_client: int = 40,
) -> WriterConcurrencyResult:
    """Concurrent insert clients against one exclusive-writer Server."""
    ensure_schema(db)
    points: list[ConcurrencyPoint] = []

    for n_clients in clients:

        def worker(client_id: int) -> list[float]:
            samples: list[float] = []
            for j in range(ops_per_client):

                def do_insert(c: int = client_id, k: int = j) -> None:
                    db.execute(
                        "INSERT INTO note (body) VALUES (?)",
                        (f"c{c}-{k}",),
                    )

                samples.append(timed_ms(do_insert))
            return samples

        t0 = time.perf_counter()
        latencies: list[float] = []
        with ThreadPoolExecutor(max_workers=n_clients) as pool:
            futures = [pool.submit(worker, i) for i in range(n_clients)]
            for fut in as_completed(futures):
                latencies.extend(fut.result())
        wall = time.perf_counter() - t0
        total_ops = n_clients * ops_per_client
        points.append(
            {
                "clients": n_clients,
                "ops": total_ops,
                "wall_s": round(wall, 3),
                "ops_per_s": round(total_ops / wall, 1) if wall else 0.0,
                "latency_ms": latency_stats(latencies),
            }
        )
    return {"scenario": "writer_concurrency", "points": points}


def multi_db_parallel(
    single: Sqlite,
    db_a: Sqlite,
    db_b: Sqlite,
    *,
    ops_per_db: int = 80,
) -> MultiDbParallelResult:
    """Single-DB sequential writes vs two DBs writing in parallel."""
    ensure_schema(single)
    ensure_schema(db_a)
    ensure_schema(db_b)

    t0 = time.perf_counter()
    for i in range(ops_per_db):
        single.execute("INSERT INTO note (body) VALUES (?)", (f"solo-{i}",))
    single_wall = time.perf_counter() - t0
    single_rate = ops_per_db / single_wall if single_wall else 0.0

    def write_many(db: Sqlite, prefix: str) -> float:
        t1 = time.perf_counter()
        for i in range(ops_per_db):
            db.execute("INSERT INTO note (body) VALUES (?)", (f"{prefix}-{i}",))
        return time.perf_counter() - t1

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(write_many, db_a, "a")
        fb = pool.submit(write_many, db_b, "b")
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
    db: Sqlite, *, sizes: tuple[int, ...] = (10, 100, 1000)
) -> BatchSizeSweepResult:
    points: list[BatchSizePoint] = []
    for size in sizes:
        db.execute("DELETE FROM note")
        t0 = time.perf_counter()
        db.executemany(
            "INSERT INTO note (body) VALUES (?)",
            [[f"sz-{size}-{i}"] for i in range(size)],
        )
        wall = time.perf_counter() - t0
        points.append(
            {
                "batch_size": size,
                "wall_s": round(wall, 4),
                "rows_per_s": round(size / wall, 1) if wall else 0.0,
            }
        )
    return {"scenario": "batch_size_sweep", "points": points}


def flush_cost(db: Sqlite, *, n: int) -> FlushCostResult:
    insert_only: list[float] = []
    insert_flush: list[float] = []
    for i in range(n):

        def do_insert(idx: int = i) -> None:
            db.execute("INSERT INTO note (body) VALUES (?)", (f"io-{idx}",))

        def do_insert_flush(idx: int = i) -> None:
            db.execute("INSERT INTO note (body) VALUES (?)", (f"if-{idx}",))
            db.flush()

        insert_only.append(timed_ms(do_insert))
        insert_flush.append(timed_ms(do_insert_flush))
    return {
        "scenario": "flush_cost",
        "n": n,
        "insert_ms": latency_stats(insert_only),
        "insert_and_flush_ms": latency_stats(insert_flush),
        "note": "flush is a sync volume.commit barrier",
    }
