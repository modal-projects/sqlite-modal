# Benchmarks

Live HTTP measurements against a warm Server (`min_containers=1`).

## Setup

Proxy tokens + `uv sync` (same as root README).

## Run

```bash
uv run modal run benchmarks/app.py
uv run modal run benchmarks/app.py --n 20 --writes 50 --batch-n 100
```

Outputs:

| Artifact | Location |
|----------|----------|
| JSON report | `benchmarks/results/latest.json` (gitignored) |
| Charts | `docs/charts/*.png` (committed for README) |

## Scenarios

| Name | What it measures |
|------|------------------|
| `rtt_floor` | `/health`, `SELECT 1`, `INSERT` latency |
| `single_vs_batch` | N single executes vs batch / `params_seq` |
| `flush_cost` | insert vs insert + `flush` |
| `throughput` | sequential write/read ops/s |

## Charts

| File | Story |
|------|--------|
| `latency.png` | RTT floor — health ≈ SQL |
| `throughput.png` | Sequential ops/s |
| `batching.png` | Why `executemany` / `batch` matter |
| `flush.png` | Sync `volume.commit` cost |

Regenerate from JSON without re-running Modal:

```bash
uv run python -c "import json; from pathlib import Path; from benchmarks.charts import render_charts; render_charts(json.loads(Path('benchmarks/results/latest.json').read_text()))"
```
