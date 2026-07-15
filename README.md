# Distributed SQLite on Modal

Multi-tenant SQLite on [Modal](https://modal.com): one exclusive writer container per named database, durable on a Volume.

This is a copyable architecture example — not a managed database product. Think of each `SqliteDatabase(db_name=…)` as a Turso-style **primary** for that name. It does not implement embedded-replica / local-first sync.

## Layout

| File | Role |
|------|------|
| [`sqlite.py`](sqlite.py) | `SqliteDatabase` — Volume writer, Class RPC, in-process HTTP |
| [`api.py`](api.py) | Notes FastAPI app (mounted on the writer) |
| [`models.py`](models.py) | SQLAlchemy schema (Alembic) |
| [`seed.py`](seed.py) / [`bench.py`](bench.py) | Seed data and load tests |

## Architecture

```text
HTTP  ──► SqliteDatabase(db_name=…).web   ← same container, local sqlite3
Workers ──.remote──► SqliteDatabase
                         hot: /tmp/sqlite/{db}.db
                         durable: Volume /data/{db}.db
```

- `max_containers=1` is **per `db_name`** (many tenants → many containers).
- Pick the DB with Modal’s Class parameter: `?db_name=tenant-acme`.
- Volume flush is background (~30s) and on exit — not on every write. A crash between flushes can lose recent commits.
- `execute` / `query` / `executemany` are for **trusted workspace callers** (arbitrary SQL).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A [Modal](https://modal.com) account (`modal setup`)

## Quickstart

```bash
uv sync
uv run modal serve sqlite.py
```

```bash
export URL=https://…-sqlitedatabase-web-dev.modal.run

curl "$URL/health?db_name=tenant-acme"
curl -X POST "$URL/notes?db_name=tenant-acme" \
  -H 'content-type: application/json' -d '{"body":"hello"}'
curl "$URL/notes?db_name=tenant-acme"
curl "$URL/notes?db_name=tenant-globex"
```

Workers (Class RPC, no HTTP hop):

```python
from sqlite import SqliteDatabase

db = SqliteDatabase(db_name="tenant-acme")
db.execute.remote("INSERT INTO note (body) VALUES (?)", ("hello",))
db.query.remote("SELECT id, body FROM note ORDER BY id LIMIT 50")
```

```bash
uv run modal run seed.py
uv run modal run bench.py   # writes bench_results.json + docs/charts/
```

## Schema

1. Edit [`models.py`](models.py)
2. `uv run alembic revision --autogenerate -m "…"`
3. Redeploy — Alembic runs on `@modal.enter`

## Gotchas

| Topic | Detail |
|-------|--------|
| Scaling | Scale by adding `db_name`s. Do not run multiple writers on one `.db`. |
| Latency | In-process HTTP is fast; chatty single-row Class RPC is ~RTT-bound — prefer batches (`executemany`). |
| Durability | Local `/tmp` first; Volume snapshots periodically. |
| Sync | No multi-replica push/pull — one primary per name. |
