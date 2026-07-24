"""Local read/write latency + throughput benchmarks.

```bash
uv sync --group bench
uv run python benchmarks/app.py --create-remotes   # once
uv run python benchmarks/app.py                    # skip cold by default
uv run python benchmarks/app.py --cold
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
    WARM_NAME,
    WARM_OPTIONS,
    resolve,
)
from benchmarks.report import build_report, write_report
from benchmarks.scenarios import (
    cold_start,
    local_latency,
    local_throughput,
    sync_latency,
)

WORKDIR = Path(__file__).resolve().parent / "results" / "workdir"


def main(
    *,
    n: int = 50,
    warmup: int = 10,
    ops: int = 500,
    sync_n: int = 20,
    cold: bool = False,
    create_remotes: bool = False,
) -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    action = "creating" if create_remotes else "looking up"
    print(f"{action} remotes…")
    bench_db = resolve(WARM_NAME, create=create_remotes, options=WARM_OPTIONS)

    cold_result = None
    if cold:
        bench_cold = resolve(COLD_NAME, create=create_remotes, options=COLD_OPTIONS)
        print(
            f"cold-start: idle {bench_cold.name} for {COLD_WAIT_S:.0f}s, "
            "then measure connect+push"
        )
        cold_result = cold_start(
            bench_cold,
            WORKDIR / "cold.db",
            scaledown_wait_s=COLD_WAIT_S,
        )
    elif create_remotes:
        resolve(COLD_NAME, create=True, options=COLD_OPTIONS)

    report = build_report(
        region=REGION,
        routing_region=ROUTING_REGION,
        local_latency=local_latency(
            bench_db, WORKDIR / "latency.db", n=n, warmup=warmup
        ),
        local_throughput=local_throughput(bench_db, WORKDIR / "throughput.db", ops=ops),
        sync_latency=sync_latency(bench_db, WORKDIR / "sync.db", n=sync_n),
        cold_start=cold_result,
    )
    print(json.dumps(report, indent=2))
    path = write_report(report)
    print(f"wrote {path}")
    for chart in render_charts(report):
        print(f"wrote {chart}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=50, help="latency samples")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--ops", type=int, default=500, help="throughput ops")
    parser.add_argument("--sync-n", type=int, default=20)
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Measure cold start on bench_cold (slow)",
    )
    parser.add_argument(
        "--create-remotes",
        action="store_true",
        help="Deploy bench / bench_cold (once)",
    )
    args = parser.parse_args()
    main(
        n=args.n,
        warmup=args.warmup,
        ops=args.ops,
        sync_n=args.sync_n,
        cold=args.cold,
        create_remotes=args.create_remotes,
    )
