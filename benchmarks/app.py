# Adoption-focused benchmarks for sqlite_modal.
#
#   uv run modal run benchmarks/app.py
#   uv run modal run benchmarks/app.py --skip-cold

from __future__ import annotations

import json

import modal

from benchmarks.charts import render_charts
from benchmarks.report import build_report, write_report
from benchmarks.scenarios import (
    ColdStartResult,
    batch_size_sweep,
    cold_start,
    ensure_schema,
    flush_cost,
    multi_db_parallel,
    warm_latency,
    writer_concurrency,
)
from sqlite_modal import Sqlite

REGION = "eu-west"
CLOUD = "aws"
COLD_SCALEDOWN_S = 15
# Wait a bit longer than scaledown_window so the cold Server can go to zero.
COLD_WAIT_S = float(COLD_SCALEDOWN_S + 20)

app = modal.App("example-sqlite-bench")

# Warm exclusive writer (most scenarios).
bench_db = Sqlite.from_name("bench")
bench_db.attach(
    app,
    region=REGION,
    cloud=CLOUD,
    min_containers=1,
)

# Scale-to-zero DB for cold-start measurement.
bench_cold = Sqlite.from_name("bench_cold")
bench_cold.attach(
    app,
    region=REGION,
    cloud=CLOUD,
    min_containers=0,
    scaledown_window=COLD_SCALEDOWN_S,
)

# Second pair for multi-DB parallel writes.
bench_a = Sqlite.from_name("bench_a")
bench_a.attach(app, region=REGION, cloud=CLOUD, min_containers=1)
bench_b = Sqlite.from_name("bench_b")
bench_b.attach(app, region=REGION, cloud=CLOUD, min_containers=1)


@app.local_entrypoint()
def main(
    n: int = 30,
    warmup: int = 10,
    ops_per_client: int = 40,
    ops_per_db: int = 80,
    flush_n: int = 10,
    skip_cold: bool = False,
) -> None:
    print("warming", bench_db.url)
    ensure_schema(bench_db)

    if skip_cold:
        cold: ColdStartResult = {
            "scenario": "cold_start",
            "cold_first_ms": 0.0,
            "warm_p50_ms": 0.0,
            "warm_n": 0,
            "note": "skipped (--skip-cold)",
        }
    else:
        print(
            f"cold-start: warm {bench_cold.url}, wait {COLD_WAIT_S:.0f}s, then probe"
        )
        cold = cold_start(bench_cold, scaledown_wait_s=COLD_WAIT_S)

    report = build_report(
        region=REGION,
        cloud=CLOUD,
        warm_latency=warm_latency(bench_db, n=n, warmup=warmup),
        cold_start=cold,
        writer_concurrency=writer_concurrency(
            bench_db, ops_per_client=ops_per_client
        ),
        multi_db_parallel=multi_db_parallel(
            bench_db, bench_a, bench_b, ops_per_db=ops_per_db
        ),
        batch_size_sweep=batch_size_sweep(bench_db),
        flush_cost=flush_cost(bench_db, n=flush_n),
    )
    print(json.dumps(report, indent=2))
    path = write_report(report)
    print(f"wrote {path}")
    for chart in render_charts(report):
        print(f"wrote {chart}")
