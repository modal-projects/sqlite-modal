"""Latency sample collection for benchmark scenarios."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from typing import TypedDict


class LatencyMs(TypedDict):
    p50: float
    p95: float
    mean: float


class Samples:
    """Accumulates millisecond timings and summarizes them."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def add(self, ms: float) -> None:
        self.values.append(ms)

    def measure(self, fn: Callable[[], object]) -> float:
        t0 = time.perf_counter()
        fn()
        ms = (time.perf_counter() - t0) * 1000
        self.values.append(ms)
        return ms

    def summary(self) -> LatencyMs:
        xs = self.values
        return {
            "p50": round(self.percentile(50), 2),
            "p95": round(self.percentile(95), 2),
            "mean": round(statistics.fmean(xs), 2) if xs else 0.0,
        }

    def percentile(self, p: float) -> float:
        xs = sorted(self.values)
        if not xs:
            return 0.0
        if len(xs) == 1:
            return xs[0]
        k = (len(xs) - 1) * (p / 100.0)
        lo = int(k)
        hi = min(lo + 1, len(xs) - 1)
        if lo == hi:
            return xs[lo]
        return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
