# Benchmark SqliteDatabase (Class RPC + in-process HTTP)
#
#   uv run modal run bench.py

import asyncio
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlite import SqliteDatabase, app

NOTE = (
    "Meeting notes {i}: reviewed launch checklist, confirmed WAL flush on exit, "
    "assigned follow-ups for tenant isolation QA, and recorded RPC p50/p95 targets "
    "for the on-call dashboard. payload_pad={pad}"
)


def note_body(i: int) -> str:
    return NOTE.format(i=i, pad=f"{i:04d}" * 8)


def percentile(samples: list[float], p: float) -> float:
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


def summarize(samples: list[float], *, n: int, wall_s: float, errors: int, **extra) -> dict:
    ok = len(samples)
    return {
        **extra,
        "n": n,
        "ok": ok,
        "errors": errors,
        "wall_s": round(wall_s, 3),
        "rps": round(ok / wall_s, 1) if wall_s else 0.0,
        "latency_ms": {
            "p50": round(percentile(samples, 50), 2),
            "p95": round(percentile(samples, 95), 2),
            "p99": round(percentile(samples, 99), 2),
            "mean": round(statistics.fmean(samples), 2) if samples else 0.0,
        },
    }


async def run_pool(ops: int, concurrency: int, call) -> tuple[list[float], int, list[str]]:
    sem = asyncio.Semaphore(concurrency)
    samples: list[float] = []
    errors = 0
    err_samples: list[str] = []

    async def one(i: int) -> None:
        nonlocal errors
        async with sem:
            try:
                samples.append(await call(i))
            except Exception as e:
                errors += 1
                if len(err_samples) < 5:
                    err_samples.append(f"{type(e).__name__}: {e}")

    await asyncio.gather(*(one(i) for i in range(ops)))
    return samples, errors, err_samples


async def measure(ops: int, concurrency: int, warmup: int, call) -> dict:
    await asyncio.gather(*(call(10_000_000 + i) for i in range(warmup)))
    t0 = time.perf_counter()
    samples, errors, err_samples = await run_pool(ops, concurrency, call)
    return summarize(
        samples,
        n=ops,
        wall_s=time.perf_counter() - t0,
        errors=errors,
        error_samples=err_samples,
        concurrency=concurrency,
        warmup=warmup,
    )


@app.function(timeout=20 * 60)
async def seed_table(db_name: str, rows: int = 500) -> int:
    db = SqliteDatabase(db_name=db_name)
    await db.execute.remote.aio("DELETE FROM note")
    inserted = 0
    for i in range(0, rows, 100):
        chunk = [(note_body(j),) for j in range(i, min(i + 100, rows))]
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
        await db.execute.remote.aio("INSERT INTO note (body) VALUES (?)", (note_body(i),))
        return (time.perf_counter() - t0) * 1000

    out = await measure(ops, concurrency, warmup, call)
    out["scenario"] = "rpc_single_writes"
    return out


@app.function(timeout=20 * 60)
async def read_bench(
    ops: int = 1000,
    concurrency: int = 64,
    db_name: str = "bench",
    warmup: int = 32,
) -> dict:
    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")
    rows = await db.query.remote.aio("SELECT id FROM note ORDER BY id LIMIT 200")
    ids = [r["id"] for r in rows] or [1]

    async def call(i: int) -> float:
        t0 = time.perf_counter()
        await db.query.remote.aio(
            "SELECT id, body FROM note WHERE id = ?", (ids[i % len(ids)],)
        )
        return (time.perf_counter() - t0) * 1000

    out = await measure(ops, concurrency, warmup, call)
    out["scenario"] = "rpc_point_reads"
    return out


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
    err_samples: list[str] = []
    for i in range(0, rows, batch):
        chunk = [(note_body(j),) for j in range(i, min(i + batch, rows))]
        try:
            await db.executemany.remote.aio("INSERT INTO note (body) VALUES (?)", chunk)
        except Exception as e:
            errors += 1
            if len(err_samples) < 5:
                err_samples.append(f"{type(e).__name__}: {e}")
    wall = time.perf_counter() - t0
    count = (await db.query.remote.aio("SELECT COUNT(*) AS n FROM note"))[0]["n"]
    return {
        "scenario": "rpc_batch_writes",
        "rows": rows,
        "batch": batch,
        "ok_rows": count,
        "errors": errors,
        "error_samples": err_samples,
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
    parallel_wall = max(ra["wall_s"], rb["wall_s"]) or (time.perf_counter() - t0)
    return {
        "scenario": "rpc_writes_two_tenants",
        "parallel_wall_s": round(parallel_wall, 3),
        "tenant_a": ra,
        "tenant_b": rb,
        "combined_rps": round((ra["ok"] + rb["ok"]) / parallel_wall, 1)
        if parallel_wall
        else 0.0,
    }


@app.function(timeout=10 * 60)
async def isolation_check() -> dict:
    a = SqliteDatabase(db_name="iso-a")
    b = SqliteDatabase(db_name="iso-b")
    await a.execute.remote.aio("DELETE FROM note")
    await b.execute.remote.aio("DELETE FROM note")
    await a.execute.remote.aio("INSERT INTO note (body) VALUES (?)", ("only-a",))
    await b.execute.remote.aio("INSERT INTO note (body) VALUES (?)", ("only-b",))
    bodies_a = [r["body"] for r in await a.query.remote.aio("SELECT body FROM note ORDER BY id")]
    bodies_b = [r["body"] for r in await b.query.remote.aio("SELECT body FROM note ORDER BY id")]
    return {
        "scenario": "tenant_isolation",
        "ok": bodies_a == ["only-a"] and bodies_b == ["only-b"],
        "tenant_a": bodies_a,
        "tenant_b": bodies_b,
    }


@app.function(timeout=20 * 60)
async def http_write_bench(
    ops: int = 500,
    concurrency: int = 64,
    db_name: str = "http-bench",
    warmup: int = 32,
) -> dict:
    import httpx

    db = SqliteDatabase(db_name=db_name)
    await db.query.remote.aio("SELECT 1 AS ok")
    base = db.web.get_web_url().rstrip("/")
    params = {"db_name": db_name}

    async with httpx.AsyncClient(timeout=60.0) as client:
        (await client.get(f"{base}/ready", params=params)).raise_for_status()

        async def call(i: int) -> float:
            t0 = time.perf_counter()
            resp = await client.post(
                f"{base}/notes",
                params=params,
                json={"body": note_body(i)},
            )
            resp.raise_for_status()
            return (time.perf_counter() - t0) * 1000

        out = await measure(ops, concurrency, warmup, call)

    out["scenario"] = "http_inprocess_writes"
    out["base_url"] = base
    out["db_name"] = db_name
    return out


def render_charts(results: dict, out_dir: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    def save_bar(name: str, title: str, ylabel: str, labels: list, vals: list, colors: list):
        fig, ax = plt.subplots(figsize=(7, 4))
        bars = ax.bar(labels, vals, color=colors[: len(labels)])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        for bar, val in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{val:.0f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
        fig.tight_layout()
        path = out_dir / name
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(str(path))

    if "writes" in results and "reads" in results:
        save_bar(
            "throughput.png",
            "Class RPC throughput",
            "ops / s",
            [results["writes"]["scenario"], results["reads"]["scenario"]]
            + (
                ["two_tenants_combined"]
                if "multi_tenant" in results
                else []
            ),
            [results["writes"]["rps"], results["reads"]["rps"]]
            + (
                [results["multi_tenant"]["combined_rps"]]
                if "multi_tenant" in results
                else []
            ),
            ["#1f6feb", "#1a7f37", "#cf222e"],
        )

    if "writes" in results and "batch_writes" in results:
        save_bar(
            "batching.png",
            "Batching amortizes RPC round-trips",
            "throughput",
            ["single-row RPC\n(ops/s)", "executemany\n(rows/s)"],
            [results["writes"]["rps"], results["batch_writes"]["rows_per_s"]],
            ["#1f6feb", "#1a7f37"],
        )

    if "writes" in results and "http_writes" in results:
        save_bar(
            "http_vs_rpc.png",
            "HTTP in-process vs Class RPC (p50 ms, lower better)",
            "latency (ms)",
            ["Class RPC", "HTTP in-process"],
            [
                results["writes"]["latency_ms"]["p50"],
                results["http_writes"]["latency_ms"]["p50"],
            ],
            ["#cf222e", "#1a7f37"],
        )

    if "multi_tenant" in results:
        mt = results["multi_tenant"]
        save_bar(
            "multi_tenant.png",
            "Two tenants → two writers (parallel)",
            "writes / s",
            ["tenant A", "tenant B", "combined"],
            [mt["tenant_a"]["rps"], mt["tenant_b"]["rps"], mt["combined_rps"]],
            ["#1f6feb", "#8250df", "#1a7f37"],
        )

    return paths


@app.local_entrypoint()
def bench(
    writes: int = 500,
    reads: int = 1000,
    http_writes: int = 500,
    ops_per_tenant: int = 250,
    concurrency: int = 64,
    batch_rows: int = 5000,
    seed_rows: int = 500,
):
    print(f"seeded {seed_table.remote('bench', seed_rows)} rows")

    out = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "concurrency": concurrency,
            "seed_rows": seed_rows,
            "note": "RPC = .remote.aio; HTTP = in-process ASGI; Volume flush is background-only.",
        },
        "isolation": isolation_check.remote(),
        "writes": write_bench.remote(writes, concurrency, "bench"),
        "reads": read_bench.remote(reads, concurrency, "bench"),
        "http_writes": http_write_bench.remote(http_writes, concurrency),
        "batch_writes": batch_write_bench.remote(batch_rows),
        "multi_tenant": multi_tenant_write_bench.remote(ops_per_tenant, concurrency),
    }
    print(json.dumps(out, indent=2))
    Path("bench_results.json").write_text(json.dumps(out, indent=2))
    for p in render_charts(out, Path("docs/charts")):
        print(f"wrote {p}")
    if not out["isolation"]["ok"]:
        raise SystemExit("tenant isolation check failed")
