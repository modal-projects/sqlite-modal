# sqlite_modal

Named SQLite on [Modal Servers](https://modal.com/docs/guide/servers):
`from_name` → `attach` → HTTP SQL (`query` / `execute` / `executemany` / `batch`).

One exclusive-writer Server + Volume per name. Many named DBs can share one App.
Clients (local or scaled Modal Functions) talk HTTP — do not mount the Volume for
writes from multiple containers.

```text
Workers / local  ──HTTP──►  SqliteServer_{name}  ──►  Volume {name}-data
                              (min_containers 0|1)         /data/db.sqlite
```

## Quickstart

```bash
uv sync

modal workspace proxy-tokens create
export MODAL_PROXY_TOKEN_ID=wk-…
export MODAL_PROXY_TOKEN_SECRET=ws-…
modal workspace proxy-tokens allow "$MODAL_PROXY_TOKEN_ID" main

uv run modal run examples/notes/app.py
```

```python
import modal
from sqlite_modal import Sqlite

app = modal.App("my-app")

db = Sqlite.from_name("orders")
db.attach(app, region="eu-west", cloud="aws")

@app.local_entrypoint()
def main() -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)"
    )
    db.executemany("INSERT INTO t (v) VALUES (?)", [["a"], ["b"], ["c"]])
    print(db.query("SELECT id, v FROM t ORDER BY id"))
    db.flush()   # optional sync barrier (~seconds); Volume also background-commits
    db.close()
```

Names: `^[A-Za-z][A-Za-z0-9_]{0,127}$`. Params: JSON scalars only (no `bytes`/BLOB).

## Layout

| Path | Role |
|------|------|
| [`sqlite_modal/`](sqlite_modal/) | Library (`Sqlite` client, HTTP API, private Server) |
| [`examples/notes/`](examples/notes/) | Single-DB smoke |
| [`examples/multi/`](examples/multi/) | Two DBs on one App |
| [`tests/`](tests/) | Unit tests (no cloud) |
| [`benchmarks/`](benchmarks/) | Live Server latency / throughput |

## API

| Member | Role |
|--------|------|
| `Sqlite.from_name(name, *, timeout=, max_retries=)` | Named DB → Volume `{name}-data` |
| `attach(app, region=, cloud=, min_containers=0\|1, …)` | Register Server on App |
| `query` / `execute` | One statement / one HTTP RTT |
| `executemany` / `batch` | Many rows or ops / one RTT (prefer for bulk) |
| `flush` | WAL checkpoint + sync `volume.commit` (~seconds) |
| `close` | Close HTTP client (Server keeps running) |
| `url` | Server URL after serve/deploy |
| Exceptions | `InvalidNameError`, `NotAttachedError`, `AlreadyAttachedError`, `AuthError`, `SqlError`, `ServiceError` |

`sqlite_modal.db.Database` is internal to the Server process — not an app API.

Modal object name for ops: `SqliteServer_{name}`.

## Performance notes

- Hot path ≈ one Modal HTTP RTT (typically tens of ms), not local SQLite.
- Loops of `execute` ≈ N × RTT; use `executemany` / `batch` for bulk.
- `flush()` ≈ seconds (sync Volume commit). Skip on the hot path unless you need a durability barrier.
- `min_containers=0` scales to zero; use `1` when first-byte latency matters.

## Develop

```bash
uv run pytest
uv run ruff check sqlite_modal examples benchmarks tests
uv run ty check sqlite_modal examples benchmarks tests
```

```bash
uv run modal run examples/multi/app.py
uv run modal run benchmarks/app.py
```
