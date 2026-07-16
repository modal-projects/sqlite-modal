"""Latency helpers and named benchmark scenarios."""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Callable
from typing import TypedDict

import httpx

from sqlite_modal import Sqlite
from sqlite_modal.db import BatchOp


class LatencyMs(TypedDict):
    p50: float
    p95: float
    mean: float


class RateResult(TypedDict):
    wall_s: float
    ops_per_s: float


class BulkRateResult(TypedDict):
    wall_s: float
    rows_per_s: float


class RttFloorResult(TypedDict):
    scenario: str
    n: int
    health_ms: LatencyMs
    select1_ms: LatencyMs
    insert_ms: LatencyMs


class SingleVsBatchResult(TypedDict):
    scenario: str
    n: int
    single_execute: RateResult
    batch_n_executes: RateResult
    batch_params_seq: BulkRateResult


class FlushCostResult(TypedDict):
    scenario: str
    n: int
    insert_ms: LatencyMs
    insert_and_flush_ms: LatencyMs
    note: str


class ThroughputSide(TypedDict):
    n: int
    wall_s: float
    ops_per_s: float
    latency_ms: LatencyMs


class ThroughputResult(TypedDict):
    scenario: str
    writes: ThroughputSide
    reads: ThroughputSide


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


def timed_ms(fn: Callable[[], None]) -> float:
    t0 = time.perf_counter()
    fn()
    return (time.perf_counter() - t0) * 1000


NOTE_DDL = (
    "CREATE TABLE IF NOT EXISTS note (id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
)


def ensure_schema(db: Sqlite) -> None:
    db.execute(NOTE_DDL)
    db.execute("DELETE FROM note")


def rtt_floor(db: Sqlite, *, n: int, warmup: int) -> RttFloorResult:
    headers = {
        "Modal-Key": os.environ["MODAL_PROXY_TOKEN_ID"],
        "Modal-Secret": os.environ["MODAL_PROXY_TOKEN_SECRET"],
    }
    url = db.url
    client = httpx.Client(timeout=60.0)
    for _ in range(warmup):
        client.get(f"{url}/health", headers=headers).raise_for_status()
        db.query("SELECT 1 AS ok")

    health: list[float] = []
    select1: list[float] = []
    insert: list[float] = []
    for i in range(n):

        def do_health() -> None:
            client.get(f"{url}/health", headers=headers).raise_for_status()

        def do_select() -> None:
            db.query("SELECT 1 AS ok")

        def do_insert(idx: int = i) -> None:
            db.execute("INSERT INTO note (body) VALUES (?)", (f"rtt-{idx}",))

        health.append(timed_ms(do_health))
        select1.append(timed_ms(do_select))
        insert.append(timed_ms(do_insert))
    return {
        "scenario": "rtt_floor",
        "n": n,
        "health_ms": latency_stats(health),
        "select1_ms": latency_stats(select1),
        "insert_ms": latency_stats(insert),
    }


def single_vs_batch(db: Sqlite, *, n: int) -> SingleVsBatchResult:
    db.execute("DELETE FROM note")
    t0 = time.perf_counter()
    for i in range(n):
        db.execute("INSERT INTO note (body) VALUES (?)", (f"s-{i}",))
    single_s = time.perf_counter() - t0

    db.execute("DELETE FROM note")
    ops: list[BatchOp] = [
        {
            "type": "execute",
            "sql": "INSERT INTO note (body) VALUES (?)",
            "params": [f"b-{i}"],
        }
        for i in range(n)
    ]
    t0 = time.perf_counter()
    db.batch(ops)
    multi_op_s = time.perf_counter() - t0

    db.execute("DELETE FROM note")
    t0 = time.perf_counter()
    db.batch(
        [
            {
                "type": "execute",
                "sql": "INSERT INTO note (body) VALUES (?)",
                "params_seq": [[f"e-{i}"] for i in range(n)],
            }
        ]
    )
    executemany_s = time.perf_counter() - t0

    return {
        "scenario": "single_vs_batch",
        "n": n,
        "single_execute": {
            "wall_s": round(single_s, 3),
            "ops_per_s": round(n / single_s, 1) if single_s else 0.0,
        },
        "batch_n_executes": {
            "wall_s": round(multi_op_s, 3),
            "ops_per_s": round(n / multi_op_s, 1) if multi_op_s else 0.0,
        },
        "batch_params_seq": {
            "wall_s": round(executemany_s, 3),
            "rows_per_s": round(n / executemany_s, 1) if executemany_s else 0.0,
        },
    }


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


def throughput(db: Sqlite, *, writes: int, reads: int, warmup: int) -> ThroughputResult:
    for i in range(warmup):
        db.execute("INSERT INTO note (body) VALUES (?)", (f"w-{i}",))

    write_samples: list[float] = []
    t0 = time.perf_counter()
    for i in range(writes):

        def do_write(idx: int = i) -> None:
            db.execute("INSERT INTO note (body) VALUES (?)", (f"tw-{idx}",))

        write_samples.append(timed_ms(do_write))
    write_wall = time.perf_counter() - t0

    ids = [
        int(r["id"])
        for r in db.query("SELECT id FROM note ORDER BY id LIMIT 200")
        if isinstance(r["id"], int)
    ]
    if not ids:
        ids = [1]
    read_samples: list[float] = []
    t0 = time.perf_counter()
    for i in range(reads):
        note_id = ids[i % len(ids)]

        def do_read(nid: int = note_id) -> None:
            db.query("SELECT id, body FROM note WHERE id = ?", (nid,))

        read_samples.append(timed_ms(do_read))
    read_wall = time.perf_counter() - t0

    return {
        "scenario": "throughput",
        "writes": {
            "n": writes,
            "wall_s": round(write_wall, 3),
            "ops_per_s": round(writes / write_wall, 1) if write_wall else 0.0,
            "latency_ms": latency_stats(write_samples),
        },
        "reads": {
            "n": reads,
            "wall_s": round(read_wall, 3),
            "ops_per_s": round(reads / read_wall, 1) if read_wall else 0.0,
            "latency_ms": latency_stats(read_samples),
        },
    }
