# Benchmarks

Adoption-oriented measurements against live Modal Servers. Answers whether
`sqlite_modal` fits a workload: warm latency, cold start, exclusive-writer
concurrency (singleton Server), multi-DB scale-out, bulk insert rate, and sync
`flush` cost.

## Run

```bash
uv sync
export MODAL_PROXY_TOKEN_ID=wk-…
export MODAL_PROXY_TOKEN_SECRET=ws-…

uv run modal run benchmarks/app.py
uv run modal run benchmarks/app.py --n 20 --skip-cold
uv run modal run benchmarks/app.py --ops-per-client 40 --ops-per-db 80
```

| Artifact | Location |
|----------|----------|
| JSON | `benchmarks/results/latest.json` (gitignored) |
| Charts | `docs/charts/*.png` |

Cold start waits for scale-to-zero (~35s). Use `--skip-cold` for a faster loop.

## Scenarios → questions

| Scenario | Adoption question |
|----------|-------------------|
| `warm_latency` | What read/write p50/p95 do I get when warm? |
| `cold_start` | What do I pay for scale-to-zero? |
| `writer_concurrency` | What happens with many clients on one DB? |
| `multi_db_parallel` | How do I get more write throughput? |
| `batch_size_sweep` | When is bulk (`executemany`) cheap? |
| `flush_cost` | What does sync durability cost? |

## Charts

| File | Measures |
|------|----------|
| `writer_concurrency.png` | Ops/s and p50 latency vs concurrent clients on one DB |
| `multi_db_scaleout.png` | 1 DB write rate vs 2 DBs combined |
| `cold_vs_warm.png` | Cold first-request ms vs warm p50 |

Batch sizes and flush land in the README characteristics table, not separate charts.

## Wiring

| Attach | Role |
|--------|------|
| `bench` | Warm DB (`min_containers=1`) for latency, concurrency, batch, flush |
| `bench_cold` | Scale-to-zero DB (`min_containers=0`) for cold start |
| `bench_a` / `bench_b` | Parallel writers for multi-DB scale-out |
