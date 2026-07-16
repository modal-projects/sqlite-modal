# Benchmarks

Live Server measurements (HTTP RTT, batching, flush, throughput).

```bash
uv sync
export MODAL_PROXY_TOKEN_ID=wk-…
export MODAL_PROXY_TOKEN_SECRET=ws-…

uv run modal run benchmarks/app.py
uv run modal run benchmarks/app.py --n 20 --writes 50 --batch-n 100
```

Writes `benchmarks/results/latest.json` (gitignored).

## Expect

| Scenario | Typical shape |
|----------|----------------|
| `rtt_floor` | `/health`, `SELECT 1`, `INSERT` ≈ tens of ms (same ballpark) |
| `single_vs_batch` | N× `execute` ≈ N× RTT; one `batch` / `params_seq` ≈ one RTT |
| `flush_cost` | insert ≈ RTT; insert+`flush` ≈ seconds (`volume.commit`) |
| `throughput` | ~1 / RTT ops/s for sequential single calls |

Uses `min_containers=1` so cold start does not dominate.
