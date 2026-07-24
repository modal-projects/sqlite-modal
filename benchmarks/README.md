# Benchmarks

Adoption measurements against Turso Sync remotes on Modal: local SQL +
`push`/`pull`, cold start after scale-to-zero, concurrent pushers, multi-DB
scale-out, bulk insert+push, and push cost vs local commit.

## Run

```bash
uv sync --group bench

# once: deploy the four bench remotes with the intended autoscaler options
uv run python benchmarks/app.py --create-remotes --skip-cold

# subsequent runs: lookup only (no redeploy)
uv run python benchmarks/app.py --skip-cold
uv run python benchmarks/app.py
uv run python benchmarks/app.py --n 20 --ops-per-client 40
```

| Artifact | Location |
|----------|----------|
| JSON | `benchmarks/results/latest.json` (gitignored) |
| Charts | `docs/charts/*.png` |

Cold start waits for scale-to-zero (~35s) then measures HTTP readiness +
connect + schema + push. Use `--skip-cold` for a faster loop.

## Layout

| Module | Role |
|--------|------|
| `replica.py` | `LocalReplica` — path lifecycle, Modal Server readiness, schema |
| `measure.py` | `Samples` — ms timings and p50/p95/mean |
| `scenarios.py` | Adoption scenarios over `LocalReplica` |
| `remotes.py` | Create options + `resolve(..., create=)` |
| `app.py` | CLI |
| `report.py` / `charts.py` | JSON + product charts |

## Scenarios → questions

| Scenario | Adoption question |
|----------|-------------------|
| `warm_latency` | Local read/write and warm push/pull p50/p95? |
| `cold_start` | What do I pay for scale-to-zero? |
| `writer_concurrency` | Many clients pushing one remote (last-push-wins)? |
| `multi_db_parallel` | More write throughput via more named DBs? |
| `batch_size_sweep` | When is bulk `executemany` + one push cheap? |
| `push_cost` | What does sync push add over local commit? |

## Remotes

| Name | Role |
|------|------|
| `bench` | Warm (`min_containers=1`) |
| `bench_cold` | Scale-to-zero (`min_containers=0`) |
| `bench_a` / `bench_b` | Parallel writers for multi-DB scale-out |

Re-run with `--create-remotes` after changing options in `remotes.py`.
