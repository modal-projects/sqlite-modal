# sqlite_modal

Named Turso Sync DBs on Modal. Local SQL via pyturso; `push` / `pull` to a
Modal `tursodb` Server; Volume holds `server.db` on exit. Not Turso Cloud.

```text
local file  --push/pull-->  SyncServer (tursodb)
                                |
                         exit → Volume /data/{name}/
```

## Setup

Python 3.12+, `uv`, Modal logged in (`modal setup`).

```bash
uv sync
uv sync --group dev    # tests / lint
uv sync --group bench  # charts
```

## Usage

```python
from sqlite_modal import Sqlite

db = Sqlite.from_name(
    "orders",
    create_if_missing=True,
    create_options={"max_containers": 1},  # recommended
)
conn = db.connect("./orders.db")
with conn:
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", ("a",))
    conn.commit()
    conn.push()
    conn.pull()
```

- `from_name` — create/lookup App `sqlite-modal-{name}` (`create_options` → `@app.server`)
- `connect(path)` — local `ConnectionSync`; waits until the Server is up
- Sync is explicit (`push` / `pull`). Conflicts are last-push-wins.
- Prefer `max_containers=1`. Use `min_containers=1` if you don’t want cold starts.

## Commands

```bash
uv run python examples/notes/app.py
uv run python examples/multi/app.py

uv run pytest
uv run ruff check sqlite_modal examples benchmarks tests
uv run ty check sqlite_modal examples benchmarks tests

uv run python benchmarks/app.py --create-remotes  # once
uv run python benchmarks/app.py
uv run python benchmarks/app.py --cold            # optional
```

Details: [benchmarks/README.md](benchmarks/README.md).

## Layout

| Path | Role |
|------|------|
| `sqlite_modal/database.py` | `Sqlite` |
| `sqlite_modal/remote.py` | `SyncServer`, deploy, `CreateOptions` |
| `sqlite_modal/turso.py` | pins + Image |
| `examples/`, `benchmarks/` | smoke + benches |

## Benchmarks

`uk` / `eu-west`, warm `bench` (`min_containers=1`):

| | |
|--|--|
| Local read / write p50 | ~0.01 ms / ~0.09 ms |
| Local read / write ops/s | ~121k / ~9.3k |
| Warm push / pull p50 | ~158 ms / ~79 ms |

![Local latency](docs/charts/latency.png)

![Sync latency](docs/charts/sync_latency.png)

![Local throughput](docs/charts/throughput.png)
