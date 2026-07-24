"""Adoption benchmarks for Turso Sync on Modal.

Lookup existing remotes by default. Deploy them once with ``--create-remotes``.

```bash
uv sync --group bench
uv run python benchmarks/app.py --create-remotes --skip-cold
uv run python benchmarks/app.py --skip-cold
uv run python benchmarks/app.py
```
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmarks.charts import render_charts
from benchmarks.remotes import (
    COLD_NAME,
    COLD_OPTIONS,
    COLD_WAIT_S,
    REGION,
    ROUTING_REGION,
    WARM_OPTIONS,
    resolve,
)
from benchmarks.report import build_report, write_report
from benchmarks.scenarios import (
    batch_size_sweep,
    cold_start,
    multi_db_parallel,
    push_cost,
    warm_latency,
    writer_concurrency,
)

WORKDIR = Path(__file__).resolve().parent / "results" / "workdir"


def main(
    *,
    n: int = 30,
    warmup: int = 10,
    ops_per_client: int = 40,
    ops_per_db: int = 80,
    push_n: int = 10,
    skip_cold: bool = False,
    create_remotes: bool = False,
) -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    action = "creating" if create_remotes else "looking up"
    print(f"{action} remotes…")
    bench_db = resolve("bench", create=create_remotes, options=WARM_OPTIONS)
    bench_a = resolve("bench_a", create=create_remotes, options=WARM_OPTIONS)
    bench_b = resolve("bench_b", create=create_remotes, options=WARM_OPTIONS)
    bench_cold = resolve(COLD_NAME, create=create_remotes, options=COLD_OPTIONS)

    cold = None
    if not skip_cold:
        print(
            f"cold-start: idle {bench_cold.name} for {COLD_WAIT_S:.0f}s, "
            "then measure readiness+connect+push"
        )
        cold = cold_start(
            bench_cold,
            WORKDIR / "cold.db",
            scaledown_wait_s=COLD_WAIT_S,
        )

    report = build_report(
        region=REGION,
        routing_region=ROUTING_REGION,
        warm_latency=warm_latency(bench_db, WORKDIR / "warm.db", n=n, warmup=warmup),
        cold_start=cold,
        writer_concurrency=writer_concurrency(
            bench_db, WORKDIR / "concurrency", ops_per_client=ops_per_client
        ),
        multi_db_parallel=multi_db_parallel(
            bench_db,
            bench_a,
            bench_b,
            WORKDIR / "multi",
            ops_per_db=ops_per_db,
        ),
        batch_size_sweep=batch_size_sweep(bench_db, WORKDIR / "batch.db"),
        push_cost=push_cost(bench_db, WORKDIR / "push_cost.db", n=push_n),
    )
    print(json.dumps(report, indent=2))
    path = write_report(report)
    print(f"wrote {path}")
    for chart in render_charts(report):
        print(f"wrote {chart}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--ops-per-client", type=int, default=40)
    parser.add_argument("--ops-per-db", type=int, default=80)
    parser.add_argument("--push-n", type=int, default=10)
    parser.add_argument("--skip-cold", action="store_true")
    parser.add_argument(
        "--create-remotes",
        action="store_true",
        help="Deploy bench / bench_a / bench_b / bench_cold (once)",
    )
    args = parser.parse_args()
    main(
        n=args.n,
        warmup=args.warmup,
        ops_per_client=args.ops_per_client,
        ops_per_db=args.ops_per_db,
        push_n=args.push_n,
        skip_cold=args.skip_cold,
        create_remotes=args.create_remotes,
    )
