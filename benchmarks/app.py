# Modal benchmark suite for sqlite_modal.
#
#   uv run modal run benchmarks/app.py
#   uv run modal run benchmarks/app.py --n 20 --writes 50

from __future__ import annotations

import json

import modal

from benchmarks.report import build_report, write_report
from benchmarks.charts import render_charts
from benchmarks.scenarios import (
    ensure_schema,
    flush_cost,
    rtt_floor,
    single_vs_batch,
    throughput,
)
from sqlite_modal import Sqlite

REGION = "eu-west"
CLOUD = "aws"

app = modal.App("example-sqlite-bench")

bench_db = Sqlite.from_name("bench")
bench_db.attach(app, region=REGION, cloud=CLOUD, min_containers=1)


@app.local_entrypoint()
def main(
    n: int = 30,
    writes: int = 100,
    reads: int = 200,
    warmup: int = 10,
    batch_n: int = 100,
) -> None:
    print("warming", bench_db.url)
    ensure_schema(bench_db)

    report = build_report(
        region=REGION,
        cloud=CLOUD,
        rtt_floor=rtt_floor(bench_db, n=n, warmup=warmup),
        single_vs_batch=single_vs_batch(bench_db, n=batch_n),
        flush_cost=flush_cost(bench_db, n=min(n, 15)),
        throughput=throughput(bench_db, writes=writes, reads=reads, warmup=warmup),
    )
    print(json.dumps(report, indent=2))
    path = write_report(report)
    print(f"wrote {path}")
    for chart in render_charts(report):
        print(f"wrote {chart}")
