"""Benchmark report schema and writers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from benchmarks.scenarios import (
    ColdStartResult,
    LocalLatencyResult,
    LocalThroughputResult,
    SyncLatencyResult,
)

RESULTS_DIR = Path(__file__).resolve().parent / "results"


class BenchMeta(TypedDict):
    timestamp: str
    region: str
    routing_region: str
    note: str


class BenchReport(TypedDict):
    meta: BenchMeta
    local_latency: LocalLatencyResult
    local_throughput: LocalThroughputResult
    sync_latency: SyncLatencyResult
    cold_start: ColdStartResult | None


def build_report(
    *,
    region: str,
    routing_region: str,
    local_latency: LocalLatencyResult,
    local_throughput: LocalThroughputResult,
    sync_latency: SyncLatencyResult,
    cold_start: ColdStartResult | None,
) -> BenchReport:
    return {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "region": region,
            "routing_region": routing_region,
            "note": (
                "Local read/write latency + throughput; "
                "sync push/pull extras; optional cold start"
            ),
        },
        "local_latency": local_latency,
        "local_throughput": local_throughput,
        "sync_latency": sync_latency,
        "cold_start": cold_start,
    }


def write_report(report: BenchReport) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / "latest.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return path
