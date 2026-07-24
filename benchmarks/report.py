"""Benchmark report schema and writers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from benchmarks.scenarios import (
    BatchSizeSweepResult,
    ColdStartResult,
    MultiDbParallelResult,
    PushCostResult,
    WarmLatencyResult,
    WriterConcurrencyResult,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class BenchMeta(TypedDict):
    timestamp: str
    region: str
    routing_region: str
    note: str


class BenchReport(TypedDict):
    meta: BenchMeta
    warm_latency: WarmLatencyResult
    cold_start: ColdStartResult | None
    writer_concurrency: WriterConcurrencyResult
    multi_db_parallel: MultiDbParallelResult
    batch_size_sweep: BatchSizeSweepResult
    push_cost: PushCostResult


def build_report(
    *,
    region: str,
    routing_region: str,
    warm_latency: WarmLatencyResult,
    cold_start: ColdStartResult | None,
    writer_concurrency: WriterConcurrencyResult,
    multi_db_parallel: MultiDbParallelResult,
    batch_size_sweep: BatchSizeSweepResult,
    push_cost: PushCostResult,
) -> BenchReport:
    return {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "region": region,
            "routing_region": routing_region,
            "note": (
                "Turso Sync on Modal: local SQL + push/pull, cold start, "
                "writer concurrency, multi-DB scale-out, batch, push cost"
            ),
        },
        "warm_latency": warm_latency,
        "cold_start": cold_start,
        "writer_concurrency": writer_concurrency,
        "multi_db_parallel": multi_db_parallel,
        "batch_size_sweep": batch_size_sweep,
        "push_cost": push_cost,
    }


def write_report(report: BenchReport) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "latest.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path
