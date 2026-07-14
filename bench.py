# # Benchmark SqliteDatabase (Class RPC)
#
# Realistic load against the same surface the Notes API uses: concurrent
# `.remote.aio` calls, warm containers, non-trivial row payloads, seeded tables,
# latency percentiles, and error accounting. Also emits PNG charts for the README.
#
# ```bash
# uv run modal run bench.py
# uv run modal run bench.py --writes 800 --reads 1200 --concurrency 64
# ```

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlite import SqliteDatabase, app

# Representative note bodies (~220–280 bytes), not tiny "w-0" strings.
_NOTE = (
    "Meeting notes {i}: reviewed launch checklist, confirmed WAL flush on exit, "
    "assigned follow-ups for tenant isolation QA, and recorded RPC p50/p95 targets "
    "for the on-call dashboard. payload_pad={pad}"
)


def _body(i: int) -> str:
    return _NOTE.format(i=i, pad=f"{i:04d}" * 8)


def _pct(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    xs = sorted(samples)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _summary(samples: list[float], *, n: int, wall_s: float, errors: int, **extra) -> dict:
    ok = len(samples)
    return {
        **extra,
        "n": n,
        "ok": ok,
        "errors": errors,
        "wall_s": round(wall_s, 3),
        "rps": round(ok / wall_s, 1) if wall_s else 0.0,
        "latency_ms": {
            "p50": round(_pct(samples, 50), 2),
            "p95": round(_pct(samples, 95), 2),
            "p99": round(_pct(samples, 99), 2),
            "mean": round(statistics.fmean(samples), 2) if samples else 0.0,
        },
    }


@app.function(timeout=20 * 60)
async def seed_table(db_name: str, rows: int = 500) -> int:
    """Pre-populate so reads hit a real table, not an empty one."""
    db = SqliteDatabase(db_name=db_name)
    # wipe prior bench data for determinism within this db_name
    await db.execute.remote.aio("DELETE FROM note")
    batch = 100
    inserted = 0
    for i in range(0, rows, batch):
        chunk = [(_body(j),) for j in range(i, min(i + batch, rows))]
        await db.executemany.remote.aio("INSERT INTO note (body) VALUES (?)", chunk)
        inserted += len(chunk)
    return inserted


@app.function(timeout=20 * 60)
async def write_bench(
    ops: int = 500,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 32,
) -> dict:
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")

    async def call(i: int) -> float:
        t0 = time.perf_counter()
        await db.execute.remote.aio("INSERT INTO note (body) VALUES (?)", (_body(i),))
        return (time.perf_counter() - t0) * 1000

    # warmup — discarded
    await asyncio.gather(*(call(10_000_000 + i) for i in range(warmup)))

    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await call(i))
            except Exception:
                errors += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(ops)))
    wall = time.perf_counter() - t0
    return _summary(
        samples,
        n=ops,
        wall_s=wall,
        errors=errors,
        scenario="rpc_single_writes",
        concurrency=concurrency,
        warmup=warmup,
    )


@app.function(timeout=20 * 60)
async def read_bench(
    ops: int = 1000,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 32,
) -> dict:
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")
    # bound ids so point lookups usually hit
    rows = await db.query.remote.aio("SELECT id FROM note ORDER BY id LIMIT 200")
    ids = [r["id"] for r in rows] or [1]

    async def call(i: int) -> float:
        note_id = ids[i % len(ids)]
        t0 = time.perf_counter()
        await db.query.remote.aio(
            "SELECT id, body FROM note WHERE id = ?", (note_id,)
        )
        return (time.perf_counter() - t0) * 1000

    await asyncio.gather(*(call(i) for i in range(warmup)))

    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await call(i))
            except Exception:
                errors += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(ops)))
    wall = time.perf_counter() - t0
    return _summary(
        samples,
        n=ops,
        wall_s=wall,
        errors=errors,
        scenario="rpc_point_reads",
        concurrency=concurrency,
        warmup=warmup,
    )


@app.function(timeout=20 * 60)
async def list_bench(
    ops: int = 400,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 16,
) -> dict:
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")

    async def call(_: int) -> float:
        t0 = time.perf_counter()
        await db.query.remote.aio(
            "SELECT id, body FROM note ORDER BY id DESC LIMIT 50"
        )
        return (time.perf_counter() - t0) * 1000

    await asyncio.gather(*(call(i) for i in range(warmup)))

    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await call(i))
            except Exception:
                errors += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(ops)))
    wall = time.perf_counter() - t0
    return _summary(
        samples,
        n=ops,
        wall_s=wall,
        errors=errors,
        scenario="rpc_list_reads",
        concurrency=concurrency,
        warmup=warmup,
    )


@app.function(timeout=20 * 60)
async def mixed_bench(
    ops: int = 600,
    concurrency: int = 64,
    write_ratio: float = 0.3,
    db_name: str = "bench",
    warmup: int = 32,
) -> dict:
    """Mixed read/write traffic — closer to API usage than pure write or read."""
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")
    rows = await db.query.remote.aio("SELECT id FROM note ORDER BY id LIMIT 200")
    ids = [r["id"] for r in rows] or [1]

    async def call(i: int) -> float:
        t0 = time.perf_counter()
        if (i % 100) < int(write_ratio * 100):
            await db.execute.remote.aio(
                "INSERT INTO note (body) VALUES (?)", (_body(i),)
            )
        else:
            note_id = ids[i % len(ids)]
            await db.query.remote.aio(
                "SELECT id, body FROM note WHERE id = ?", (note_id,)
            )
        return (time.perf_counter() - t0) * 1000

    await asyncio.gather(*(call(10_000_000 + i) for i in range(warmup)))

    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await call(i))
            except Exception:
                errors += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(ops)))
    wall = time.perf_counter() - t0
    return _summary(
        samples,
        n=ops,
        wall_s=wall,
        errors=errors,
        scenario="rpc_mixed_30w_70r",
        concurrency=concurrency,
        write_ratio=write_ratio,
        warmup=warmup,
    )


@app.function(timeout=20 * 60)
async def batch_write_bench(
    rows: int = 5000,
    batch: int = 200,
    db_name: str = "bench-batch",
) -> dict:
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")
    await db.execute.remote.aio("DELETE FROM note")

    t0 = time.perf_counter()
    errors = 0
    for i in range(0, rows, batch):
        chunk = [(_body(j),) for j in range(i, min(i + batch, rows))]
        try:
            await db.executemany.remote.aio(
                "INSERT INTO note (body) VALUES (?)", chunk
            )
        except Exception:
            errors += 1
    wall = time.perf_counter() - t0
    count = (
        await db.query.remote.aio("SELECT COUNT(*) AS n FROM note")
    )[0]["n"]
    return {
        "scenario": "rpc_batch_writes",
        "rows": rows,
        "batch": batch,
        "ok_rows": count,
        "errors": errors,
        "wall_s": round(wall, 3),
        "rows_per_s": round(count / wall, 1) if wall else 0.0,
    }


@app.function(timeout=20 * 60)
async def multi_tenant_write_bench(
    ops_per: int = 250,
    concurrency: int = 64,
) -> dict:
    t0 = time.perf_counter()
    a = await write_bench.spawn.aio(ops_per, concurrency, "bench-a", 16)
    b = await write_bench.spawn.aio(ops_per, concurrency, "bench-b", 16)
    ra, rb = await asyncio.gather(a.get.aio(), b.get.aio())
    parent_wall = time.perf_counter() - t0
    # Throughput across both DBs over the slower tenant's measured window (not parent
    # scheduling time, which includes Function cold-start).
    parallel_wall = max(ra["wall_s"], rb["wall_s"]) or parent_wall
    return {
        "scenario": "rpc_writes_two_tenants",
        "parent_wall_s": round(parent_wall, 3),
        "parallel_wall_s": round(parallel_wall, 3),
        "tenant_a": ra,
        "tenant_b": rb,
        "combined_rps": round((ra["ok"] + rb["ok"]) / parallel_wall, 1)
        if parallel_wall
        else 0.0,
    }


@app.function(timeout=10 * 60)
async def isolation_check() -> dict:
    """Prove tenant DBs do not share rows."""
    a = SqliteDatabase(db_name="iso-a")
    b = SqliteDatabase(db_name="iso-b")
    await a.execute.remote.aio("DELETE FROM note")
    await b.execute.remote.aio("DELETE FROM note")
    await a.execute.remote.aio(
        "INSERT INTO note (body) VALUES (?)", ("only-a",)
    )
    await b.execute.remote.aio(
        "INSERT INTO note (body) VALUES (?)", ("only-b",)
    )
    ra = await a.query.remote.aio("SELECT body FROM note ORDER BY id")
    rb = await b.query.remote.aio("SELECT body FROM note ORDER BY id")
    bodies_a = [r["body"] for r in ra]
    bodies_b = [r["body"] for r in rb]
    ok = bodies_a == ["only-a"] and bodies_b == ["only-b"]
    return {
        "scenario": "tenant_isolation",
        "ok": ok,
        "tenant_a": bodies_a,
        "tenant_b": bodies_b,
    }


def _render_charts(results: dict, out_dir: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    # Throughput
    scenarios = []
    rps_vals = []
    for key in ("writes", "reads", "lists", "mixed"):
        if key in results and "rps" in results[key]:
            scenarios.append(results[key]["scenario"])
            rps_vals.append(results[key]["rps"])
    if "multi_tenant" in results:
        scenarios.append("two_tenants_combined")
        rps_vals.append(results["multi_tenant"]["combined_rps"])

    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#1f6feb", "#1a7f37", "#9a6700", "#8250df", "#cf222e", "#6e7781"]
    bars = ax.bar(scenarios, rps_vals, color=colors[: len(scenarios)])
    ax.set_ylabel("Completed ops / second")
    ax.set_title("SqliteDatabase Class RPC throughput")
    ax.tick_params(axis="x", rotation=20)
    for bar, val in zip(bars, rps_vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{val:.0f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    fig.tight_layout()
    p = out_dir / "throughput.png"
    fig.savefig(p, dpi=140)
    plt.close(fig)
    paths.append(str(p))

    # Latency percentiles
    lat_scenarios = []
    p50, p95, p99 = [], [], []
    for key in ("writes", "reads", "lists", "mixed"):
        if key in results and "latency_ms" in results[key]:
            lat_scenarios.append(results[key]["scenario"])
            lat = results[key]["latency_ms"]
            p50.append(lat["p50"])
            p95.append(lat["p95"])
            p99.append(lat["p99"])
    if lat_scenarios:
        import numpy as np

        x = np.arange(len(lat_scenarios))
        w = 0.25
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.bar(x - w, p50, w, label="p50", color="#1f6feb")
        ax.bar(x, p95, w, label="p95", color="#9a6700")
        ax.bar(x + w, p99, w, label="p99", color="#cf222e")
        ax.set_xticks(x)
        ax.set_xticklabels(lat_scenarios, rotation=20)
        ax.set_ylabel("Latency (ms)")
        ax.set_title("Class RPC client latency percentiles")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "latency.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    # Batch rows/s vs single-row write RPS (different units — dual annotation chart)
    if "batch_writes" in results and "writes" in results:
        fig, ax = plt.subplots(figsize=(7, 4))
        labels = ["single-row write\n(RPC ops/s)", "executemany batch\n(rows/s)"]
        vals = [results["writes"]["rps"], results["batch_writes"]["rows_per_s"]]
        bars = ax.bar(labels, vals, color=["#1f6feb", "#1a7f37"])
        ax.set_ylabel("Throughput")
        ax.set_title("Batching amortizes Modal RPC round-trips")
        for bar, val in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{val:,.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
            )
        fig.tight_layout()
        p = out_dir / "batching.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    # Multi-tenant parallelism
    if "multi_tenant" in results:
        mt = results["multi_tenant"]
        fig, ax = plt.subplots(figsize=(7, 4))
        labels = ["tenant A", "tenant B", "combined wall"]
        vals = [
            mt["tenant_a"]["rps"],
            mt["tenant_b"]["rps"],
            mt["combined_rps"],
        ]
        bars = ax.bar(labels, vals, color=["#1f6feb", "#8250df", "#1a7f37"])
        ax.set_ylabel("Writes / second")
        ax.set_title("Two tenants → two writer containers (parallel)")
        for bar, val in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{val:.0f}",
                ha="center",
                va="bottom",
            )
        fig.tight_layout()
        p = out_dir / "multi_tenant.png"
        fig.savefig(p, dpi=140)
        plt.close(fig)
        paths.append(str(p))

    return paths


@app.local_entrypoint()
def bench(
    writes: int = 500,
    reads: int = 1000,
    lists: int = 400,
    mixed: int = 600,
    ops_per_tenant: int = 250,
    concurrency: int = 64,
    batch_rows: int = 5000,
    seed_rows: int = 500,
):
    # Seed first so point/list/mixed reads are meaningful.
    seeded = seed_table.remote("bench", seed_rows)
    print(f"seeded bench table with {seeded} rows")

    out = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "concurrency": concurrency,
            "seed_rows": seed_rows,
            "note": (
                "Client-perceived Class RPC latency from a warm Modal Function. "
                "Payloads ~250B. Warmup ops discarded. Errors counted."
            ),
        },
        "isolation": isolation_check.remote(),
        "writes": write_bench.remote(writes, concurrency, "bench"),
        "reads": read_bench.remote(reads, concurrency, "bench"),
        "lists": list_bench.remote(lists, concurrency, "bench"),
        "mixed": mixed_bench.remote(mixed, concurrency, 0.3, "bench"),
        "batch_writes": batch_write_bench.remote(batch_rows),
        "multi_tenant": multi_tenant_write_bench.remote(ops_per_tenant, concurrency),
    }
    print(json.dumps(out, indent=2))

    results_path = Path("bench_results.json")
    results_path.write_text(json.dumps(out, indent=2))
    print(f"wrote {results_path}")

    chart_dir = Path("docs/charts")
    written = _render_charts(out, chart_dir)
    for p in written:
        print(f"wrote {p}")

    if not out["isolation"]["ok"]:
        raise SystemExit("tenant isolation check failed")
