# Benchmarks

Local read/write **latency** and **throughput** against a warm Turso Sync
remote on Modal. Sync push/pull (and optional cold start) are table extras,
not charts.

## Run

```bash
uv sync --group bench

# once: deploy bench (+ bench_cold for --cold)
uv run python benchmarks/app.py --create-remotes

uv run python benchmarks/app.py
uv run python benchmarks/app.py --cold
uv run python benchmarks/app.py --n 50 --ops 500
```

| Artifact | Location |
|----------|----------|
| JSON | `benchmarks/results/latest.json` (gitignored) |
| Charts | `docs/charts/latency.png`, `sync_latency.png`, `throughput.png` |

## Scenarios

| Scenario | Question |
|----------|----------|
| `local_latency` | Local `SELECT` / `INSERT+commit` p50/p95? |
| `local_throughput` | Sustained local read / write ops/s? |
| `sync_latency` | Warm `push` / `pull` p50? (chart + table) |
| `cold_start` | First connect+push after scale-to-zero? (`--cold`) |

## Remotes

| Name | Role |
|------|------|
| `bench` | Warm (`min_containers=1`) |
| `bench_cold` | Scale-to-zero; only needed for `--cold` |

Re-run with `--create-remotes` after changing options in `remotes.py`.
