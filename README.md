# sqlite_modal

Turso Sync on Modal: a named resource (`Sqlite.from_name`) backed by one
Modal Server per database running `tursodb --sync-server`.

```text
  client local file  --push/pull-->  tursodb (Modal Server)
                                           |
                                    exit: stop + copy
                                           v
                                    Volume /data/{name}/server.db
```

## Quickstart

```bash
uv sync
```

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

| Turso | This library |
|-------|----------------|
| Remote URL | `Sqlite.from_name("orders")` → `db.url` |
| Auth token | None (`unauthenticated` Server) |
| `turso.sync.connect(path, remote_url=…)` | `db.connect(path)` (waits for Server) |
| `push` / `pull` / `checkpoint` | Unchanged on `conn` |

`create_if_missing=True` creates the shared data Volume and deploys the
Server App (`sqlite-modal-{name}`). Lookup-only `from_name("orders")` is lazy
until `url` / `connect`. Prefer one long-lived connection; call
`push` / `pull` when needed.

`connect` blocks until the Server answers (scale-from-zero may take a few
seconds). Set `min_containers` in `create_options` if you want a warm pool.

No auto-sync on close. Conflicts are **last push wins**
([docs](https://docs.turso.tech/sync/conflict-resolution)).

## Layout

```text
sqlite_modal/
  database.py   # Sqlite handle
  remote.py     # SyncServer + deploy (used by from_name)
  turso.py      # pins + Image
  exceptions.py
```

## Examples

```bash
uv run python examples/notes/app.py
uv run python examples/multi/app.py
```

## Tests

```bash
uv run pytest
uv run ruff check sqlite_modal examples benchmarks tests
uv run ty check sqlite_modal examples benchmarks tests
```

## Benchmarks

```bash
uv sync --group bench
uv run python benchmarks/app.py --skip-cold
```
