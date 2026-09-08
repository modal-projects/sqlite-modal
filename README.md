# sqlite-modal

Named SQLite databases on [Modal](https://modal.com). Local SQL against a
file; `push` / `pull` to a Server in your workspace. A Volume holds the
remote file on exit. Sync uses the [Turso](https://docs.turso.tech/sdk/python/sync) SDK.

You create named DBs in your Modal workspace. This is not a managed
multi-tenant service.

```text
local file  --push/pull-->  SyncServer
                                |
                         exit → Volume /data
```

Local SQL stays on your machine. Sync is an explicit hop to a warm Server
in eu-west.

<p align="center">
  <img src="docs/charts/latency.png" alt="Local SQL latency: read 0.01 ms p50, write 0.09 ms p50" width="48%" />
  <img src="docs/charts/throughput.png" alt="Local SQL throughput: 121k reads/s, 9.3k writes/s" width="48%" />
</p>

Reads are about 0.01 ms and 121k/s. A local commit is about 0.09 ms.

<p align="center">
  <img src="docs/charts/sync_latency.png" alt="Warm sync latency: push 158 ms p50, pull 79 ms p50" width="72%" />
</p>

Warm push / pull is about 158 ms / 79 ms. Conflicts are last-push-wins.

## Install

Python >= 3.12 and a Modal account (`modal setup`).

```bash
uv add git+https://github.com/modal-projects/sqlite-modal.git
```

Deploy from a checkout (or editable install) so Image builds can
`add_local_python_source("sqlite_modal")`. PyPI is not set up yet.

```bash
uv sync
uv sync --group dev    # tests / lint
uv sync --group bench  # charts
```

## Usage

```python
from sqlite_modal import Sqlite

db = Sqlite.from_name("orders", create_if_missing=True)
conn = db.connect("./orders.db")
with conn:
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("INSERT INTO t VALUES (?)", ("a",))
    conn.commit()
    conn.push()
    conn.pull()
```

- `from_name` creates or looks up App `sqlite-modal-{name}` (`create_options` → `@app.server`)
- One SyncServer container per name. `max_containers` is fixed at 1.
- `connect(path)` opens a local connection and waits until the Server is up
- Sync is explicit (`push` / `pull`). Conflicts are last-push-wins.
- Use `min_containers=1` if you don't want cold starts.
- The sync URL is unauthenticated. Anyone who has it can `push` / `pull`.
- Volume persist runs when the Server exits.

## Examples

```bash
uv run python examples/notes/app.py
uv run python examples/multi/app.py
```

| Kit | When |
|-----|------|
| [`examples/notes/`](examples/notes/) | One named DB |
| [`examples/multi/`](examples/multi/) | Two Apps, two names |

## Development

```bash
uv run pytest
uv run ruff check sqlite_modal examples benchmarks tests
uv run ty check sqlite_modal examples benchmarks tests

uv run python benchmarks/app.py --create-remotes  # once
uv run python benchmarks/app.py
uv run python benchmarks/app.py --cold            # optional
```

Details: [benchmarks/README.md](benchmarks/README.md).

CI is GitHub Actions on `ubuntu-latest`.

## License

[Apache License 2.0](LICENSE)
