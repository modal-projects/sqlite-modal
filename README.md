# sqlite_modal

Internal library: Turso Sync databases as named Modal resources
(`Sqlite.from_name`), with local `turso.sync` clients and Volume-backed
`server.db`.

## Overview

Thin adapter over Modal Server + pyturso — not Turso Cloud, not a custom sync
engine. Modal owns naming, hosting `tursodb --sync-server`, and cold storage.
Turso owns `push` / `pull` / `checkpoint`. Use when you want embedded SQLite
with sync between local files and a Modal-hosted remote.

### Dependencies

- **Upstream**: Modal (`Server`, `Volume`, `App.deploy`), pyturso /
  `tursodb` (pinned in `sqlite_modal/turso.py`)
- **Downstream**: Examples and benches in this repo; any app that imports
  `sqlite_modal`

## Setup

### Prerequisites

- Python ≥ 3.12
- `uv`
- Modal CLI logged in (`modal setup`) against a workspace that can deploy
  Servers

### Install

```bash
uv sync                 # library + runtime deps
uv sync --group dev     # + pytest / ruff / ty
uv sync --group bench   # + matplotlib for charts
```

No project env vars required. Modal auth comes from the CLI / token
environment.

## Usage

```python
from sqlite_modal import Sqlite

db = Sqlite.from_name(
    "orders",
    create_if_missing=True,
    create_options={
        "max_containers": 1,  # one server.db — recommended
        # any @app.server kwarg: compute_region, min_containers, …
    },
)
conn = db.connect("./orders.db")
with conn:
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", ("a",))
    conn.commit()
    conn.push()
    conn.pull()
```

| Need | API |
|------|-----|
| Create / lookup remote | `Sqlite.from_name(name, create_if_missing=, create_options=)` |
| Sync URL | `db.url` |
| Local connection | `db.connect(path)` → `ConnectionSync` (waits for non-503) |
| Sync | `conn.push()` / `conn.pull()` / `conn.checkpoint()` |

`create_if_missing=True` ensures Volume `sqlite-modal-data` and deploys App
`sqlite-modal-{name}` with class `SyncServer`. Lookup-only `from_name` is
lazy until `url` / `connect`. No auto-sync on close. Conflicts are **last
push wins**.

## Architecture

```text
  client local file  --push/pull-->  tursodb (Modal SyncServer)
                                           |
                                    @modal.exit: stop + copy
                                           v
                                    Volume /data/{name}/server.db*
```

| Path | Purpose |
|------|---------|
| `sqlite_modal/database.py` | `Sqlite` handle |
| `sqlite_modal/remote.py` | `SyncServer`, `ServerStore`, `RemoteApp.deploy`, `CreateOptions` |
| `sqlite_modal/turso.py` | Version pins, Image, constants |
| `sqlite_modal/exceptions.py` | `SqliteError` hierarchy |
| `examples/` | Smoke apps |
| `benchmarks/` | Adoption suite → JSON + `docs/charts/` |

## Runbooks

### Smoke

```bash
uv run python examples/notes/app.py
uv run python examples/multi/app.py
```

### Tests / lint

```bash
uv run pytest
uv run ruff check sqlite_modal examples benchmarks tests
uv run ty check sqlite_modal examples benchmarks tests
```

### Benchmarks

```bash
uv run python benchmarks/app.py --create-remotes   # once (deploys bench_*)
uv run python benchmarks/app.py                    # full suite + cold
uv run python benchmarks/app.py --skip-cold
```

See [benchmarks/README.md](benchmarks/README.md). JSON →
`benchmarks/results/latest.json` (gitignored); PNGs → `docs/charts/`.

### Redeploy a named DB

```python
Sqlite.from_name("orders", create_if_missing=True, create_options={...})
```

Re-running with `create_if_missing=True` redeploys the App (picks up Image /
`SyncServer` changes). After renaming the Server class, recreate remotes
(benches: `--create-remotes`).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `MissingError` on `from_name` | App / Server not deployed | `create_if_missing=True` or `--create-remotes` |
| `connect` hangs / `TimeoutError` | Scale-to-zero 503s, or wrong Server name | Wait, or set `min_containers=1`; recreate after `SyncServer` renames |
| Data missing after scale-down | Volume save is exit-only | Expect restore on next cold start; don’t treat every `push` as Volume durable |
| Concurrent writers disagree | Last push wins | One writer per name, or shard across names |
| `ty` can’t resolve matplotlib | Bench extra not installed | `uv sync --group bench` (CI syncs both `dev` and `bench`) |

## Benchmark snapshot

Recent `uk` / `eu-west` run (`min_containers=1` unless noted):

| Metric | Value |
|--------|-------|
| Local read / write p50 | ~0.05 ms / ~0.2 ms |
| Warm push / pull p50 | ~169 ms / ~80 ms |
| Insert + push p50 | ~153 ms |
| Cold first connect+push | ~5.6 s |
| Warm push after cold | ~157 ms p50 |
| 1000-row `executemany` + push | ~2.4k rows/s |
| 16 push clients (one DB) | ~67 ops/s, p50 ~190 ms |
| 2 DBs in parallel | ~1.9× single-DB rate |

Local SQL vs warm sync (separate scales — local is sub-ms):

![Warm latency](docs/charts/warm_latency.png)

Ops/s and insert+push p50 vs concurrent clients on one remote:

![Writer concurrency](docs/charts/writer_concurrency.png)

Push-write rate: one named DB vs two in parallel:

![Multi-DB scale-out](docs/charts/multi_db_scaleout.png)

First connect+push after scale-to-zero vs warm push p50:

![Cold vs warm](docs/charts/cold_vs_warm.png)
