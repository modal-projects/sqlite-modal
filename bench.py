# Benchmark SqliteDatabase via the same Class RPC surface app code uses.
#
#   uv sync
#   uv run modal run bench.py

import asyncio
import json
import statistics
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from sqlite import PLACEMENT, REGION, ROUTING_REGION, SqliteDatabase, app

NOTE_TEMPLATE = (
    "Meeting notes {i}: reviewed launch checklist, confirmed WAL flush on exit, "
    "assigned follow-ups for tenant isolation QA, and recorded RPC p50/p95 targets "
    "for the on-call dashboard. payload_pad={pad}"
)

Op = Callable[[int], Awaitable[float]]


def open_db(db_name: str) -> SqliteDatabase:
    # Modal injects Class parameters; static checkers see a plain object type.
    cls = cast(Any, SqliteDatabase)
    return cls(db_name=db_name)


class LatencyMs(TypedDict):
    p50: float
    p95: float
    p99: float
    mean: float


class LatencyResult(TypedDict):
    scenario: str
    n: int
    ok: int
    errors: int
    error_samples: list[str]
    wall_s: float
    rps: float
    latency_ms: LatencyMs
    concurrency: int
    warmup: int


class BatchResult(TypedDict):
    scenario: str
    rows: int
    batch: int
    ok_rows: int
    errors: int
    error_samples: list[str]
    wall_s: float
    rows_per_s: float


class IsolationResult(TypedDict):
    scenario: str
    ok: bool
    tenant_a: list[str]
    tenant_b: list[str]


class MultiTenantResult(TypedDict):
    scenario: str
    parallel_wall_s: float
    tenant_a: LatencyResult
    tenant_b: LatencyResult
    combined_rps: float


class BenchMeta(TypedDict):
    timestamp: str
    concurrency: int
    seed_rows: int
    region: str
    routing_region: str
    note: str


class BenchReport(TypedDict):
    meta: BenchMeta
    isolation: IsolationResult
    writes: LatencyResult
    reads: LatencyResult
    batch_writes: BatchResult
    multi_tenant: MultiTenantResult


def note_body(i: int) -> str:
    return NOTE_TEMPLATE.format(i=i, pad=f"{i:04d}" * 8)


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
        "p99": round(percentile(samples, 99), 2),
        "mean": round(statistics.fmean(samples), 2) if samples else 0.0,
    }


async def timed_pool(
    ops: int,
    concurrency: int,
    op: Op,
) -> tuple[list[float], int, list[str]]:
    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0
    error_samples: list[str] = []

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await op(i))
            except Exception as e:
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append(f"{type(e).__name__}: {e}")

    await asyncio.gather(*(one(i) for i in range(ops)))
    return samples, errors, error_samples


async def run_latency_bench(
    *,
    scenario: str,
    ops: int,
    concurrency: int,
    warmup: int,
    op: Op,
) -> LatencyResult:
    await asyncio.gather(*(op(10_000_000 + i) for i in range(warmup)))
    t0 = time.perf_counter()
    samples, errors, error_samples = await timed_pool(ops, concurrency, op)
    wall_s = time.perf_counter() - t0
    ok = len(samples)
    return {
        "scenario": scenario,
        "n": ops,
        "ok": ok,
        "errors": errors,
        "error_samples": error_samples,
        "wall_s": round(wall_s, 3),
        "rps": round(ok / wall_s, 1) if wall_s else 0.0,
        "latency_ms": latency_stats(samples),
        "concurrency": concurrency,
        "warmup": warmup,
    }


async def warm(db: SqliteDatabase) -> None:
    await db.query.remote.aio("SELECT 1 AS ok")


@app.function(timeout=20 * 60, **PLACEMENT)
async def seed_table(db_name: str, rows: int = 500) -> int:
    db = open_db(db_name)
    await db.execute.remote.aio("DELETE FROM note")
    inserted = 0
    for i in range(0, rows, 100):
        chunk = [(note_body(j),) for j in range(i, min(i + 100, rows))]
        await db.executemany.remote.aio("INSERT INTO note (body) VALUES (?)", chunk)
        inserted += len(chunk)
    return inserted


async def _write_bench(
    ops: int,
    concurrency: int,
    db_name: str,
    warmup: int,
) -> LatencyResult:
    db = open_db(db_name)
    await warm(db)

    async def op(i: int) -> float:
        t0 = time.perf_counter()
        await db.execute.remote.aio(
            "INSERT INTO note (body) VALUES (?)", (note_body(i),)
        )
        return (time.perf_counter() - t0) * 1000

    return await run_latency_bench(
        scenario="rpc_single_writes",
        ops=ops,
        concurrency=concurrency,
        warmup=warmup,
        op=op,
    )


@app.function(timeout=20 * 60, **PLACEMENT)
async def write_bench(
    ops: int = 500,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 32,
) -> LatencyResult:
    return await _write_bench(ops, concurrency, db_name, warmup)


@app.function(timeout=20 * 60, **PLACEMENT)
async def read_bench(
    ops: int = 1000,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 32,
) -> LatencyResult:
    db = open_db(db_name)
    await warm(db)
    rows = await db.query.remote.aio("SELECT id FROM note ORDER BY id LIMIT 200")
    ids = [int(r["id"]) for r in rows] or [1]

    async def op(i: int) -> float:
        t0 = time.perf_counter()
        await db.query.remote.aio(
            "SELECT id, body FROM note WHERE id = ?", (ids[i % len(ids)],)
        )
        return (time.perf_counter() - t0) * 1000

    return await run_latency_bench(
        scenario="rpc_point_reads",
        ops=ops,
        concurrency=concurrency,
        warmup=warmup,
        op=op,
    )


@app.function(timeout=20 * 60, **PLACEMENT)
async def batch_write_bench(
    rows: int = 5000,
    batch: int = 200,
    db_name: str = "bench-batch",
) -> BatchResult:
    db = open_db(db_name)
    await warm(db)
    await db.execute.remote.aio("DELETE FROM note")

    t0 = time.perf_counter()
    errors = 0
    error_samples: list[str] = []
    for i in range(0, rows, batch):
        chunk = [(note_body(j),) for j in range(i, min(i + batch, rows))]
        try:
            await db.executemany.remote.aio("INSERT INTO note (body) VALUES (?)", chunk)
        except Exception as e:
            errors += 1
            if len(error_samples) < 5:
                error_samples.append(f"{type(e).__name__}: {e}")
    wall_s = time.perf_counter() - t0
    count_rows = await db.query.remote.aio("SELECT COUNT(*) AS n FROM note")
    ok_rows = int(count_rows[0]["n"])
    return {
        "scenario": "rpc_batch_writes",
        "rows": rows,
        "batch": batch,
        "ok_rows": ok_rows,
        "errors": errors,
        "error_samples": error_samples,
        "wall_s": round(wall_s, 3),
        "rows_per_s": round(ok_rows / wall_s, 1) if wall_s else 0.0,
    }


@app.function(timeout=20 * 60, **PLACEMENT)
async def multi_tenant_write_bench(
    ops_per: int = 250,
    concurrency: int = 64,
) -> MultiTenantResult:
    # In-process gather: .spawn() is unsupported on non-us-east routing_region.
    tenant_a, tenant_b = await asyncio.gather(
        _write_bench(ops_per, concurrency, "bench-a", 16),
        _write_bench(ops_per, concurrency, "bench-b", 16),
    )
    parallel_wall = max(tenant_a["wall_s"], tenant_b["wall_s"])
    combined = tenant_a["ok"] + tenant_b["ok"]
    return {
        "scenario": "rpc_writes_two_tenants",
        "parallel_wall_s": round(parallel_wall, 3),
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "combined_rps": round(combined / parallel_wall, 1) if parallel_wall else 0.0,
    }


@app.function(timeout=10 * 60, **PLACEMENT)
async def isolation_check() -> IsolationResult:
    a = open_db("iso-a")
    b = open_db("iso-b")
    await a.execute.remote.aio("DELETE FROM note")
    await b.execute.remote.aio("DELETE FROM note")
    await a.execute.remote.aio("INSERT INTO note (body) VALUES (?)", ("only-a",))
    await b.execute.remote.aio("INSERT INTO note (body) VALUES (?)", ("only-b",))
    ra = await a.query.remote.aio("SELECT body FROM note ORDER BY id")
    rb = await b.query.remote.aio("SELECT body FROM note ORDER BY id")
    tenant_a = [str(r["body"]) for r in ra]
    tenant_b = [str(r["body"]) for r in rb]
    return {
        "scenario": "tenant_isolation",
        "ok": tenant_a == ["only-a"] and tenant_b == ["only-b"],
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
    }


def render_charts(report: BenchReport, out_dir: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def save_bar(
        filename: str,
        title: str,
        ylabel: str,
        labels: list[str],
        values: list[float],
        colors: list[str],
    ) -> None:
        fig, ax = plt.subplots(figsize=(7, 4))
        bars = ax.bar(labels, values, color=colors[: len(labels)])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        for bar, val in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{val:.0f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        fig.tight_layout()
        path = out_dir / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        written.append(path)

    writes = report["writes"]
    reads = report["reads"]
    batch = report["batch_writes"]
    multi = report["multi_tenant"]

    save_bar(
        "throughput.png",
        "Class RPC throughput",
        "ops / s",
        [writes["scenario"], reads["scenario"], "two_tenants_combined"],
        [writes["rps"], reads["rps"], multi["combined_rps"]],
        ["#1f6feb", "#1a7f37", "#cf222e"],
    )
    save_bar(
        "latency.png",
        "Class RPC client latency (p50)",
        "ms",
        ["writes", "reads"],
        [writes["latency_ms"]["p50"], reads["latency_ms"]["p50"]],
        ["#1f6feb", "#1a7f37"],
    )
    save_bar(
        "batching.png",
        "Batching amortizes RPC round-trips",
        "throughput",
        ["single-row RPC\n(ops/s)", "executemany\n(rows/s)"],
        [writes["rps"], batch["rows_per_s"]],
        ["#1f6feb", "#1a7f37"],
    )
    save_bar(
        "multi_tenant.png",
        "Two tenants → two writers (parallel)",
        "writes / s",
        ["tenant A", "tenant B", "combined"],
        [multi["tenant_a"]["rps"], multi["tenant_b"]["rps"], multi["combined_rps"]],
        ["#1f6feb", "#8250df", "#1a7f37"],
    )
    return written


@app.local_entrypoint()
def bench(
    writes: int = 500,
    reads: int = 1000,
    ops_per_tenant: int = 250,
    concurrency: int = 64,
    batch_rows: int = 5000,
    seed_rows: int = 500,
) -> None:
    print(f"seeded {seed_table.remote('bench', seed_rows)} rows")

    report: BenchReport = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "concurrency": concurrency,
            "seed_rows": seed_rows,
            "region": REGION,
            "routing_region": ROUTING_REGION,
            "note": "Measures Class RPC (.remote.aio) against SqliteDatabase — same API as workers.",
        },
        "isolation": isolation_check.remote(),
        "writes": write_bench.remote(writes, concurrency, "bench"),
        "reads": read_bench.remote(reads, concurrency, "bench"),
        "batch_writes": batch_write_bench.remote(batch_rows),
        "multi_tenant": multi_tenant_write_bench.remote(ops_per_tenant, concurrency),
    }

    print(json.dumps(report, indent=2))
    Path("bench_results.json").write_text(json.dumps(report, indent=2))
    for path in render_charts(report, Path("docs/charts")):
        print(f"wrote {path}")
    if not report["isolation"]["ok"]:
        raise SystemExit("tenant isolation check failed")
