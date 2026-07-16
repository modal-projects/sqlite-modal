"""Benchmark report schema and writers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from benchmarks.scenarios import (
    FlushCostResult,
    RttFloorResult,
    SingleVsBatchResult,
    ThroughputResult,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class BenchMeta(TypedDict):
    timestamp: str
    region: str
    cloud: str
    note: str


class BenchReport(TypedDict):
    meta: BenchMeta
    rtt_floor: RttFloorResult
    single_vs_batch: SingleVsBatchResult
    flush_cost: FlushCostResult
    throughput: ThroughputResult


def build_report(
    *,
    region: str,
    cloud: str,
    rtt_floor: RttFloorResult,
    single_vs_batch: SingleVsBatchResult,
    flush_cost: FlushCostResult,
    throughput: ThroughputResult,
) -> BenchReport:
    return {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "region": region,
            "cloud": cloud,
            "note": (
                "Modal Server HTTP; flush=sync volume.commit; "
                "Volume also background-commits"
            ),
        },
        "rtt_floor": rtt_floor,
        "single_vs_batch": single_vs_batch,
        "flush_cost": flush_cost,
        "throughput": throughput,
    }


def write_report(report: BenchReport) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "latest.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path
