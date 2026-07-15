# Distributed SQLite on Modal

Architecture demo: **one exclusive writer per named database**, many databases in parallel.
Not a managed database product.

### Goals

- Multi-tenant SQLite on Modal Volumes without multi-writer corruption
- Scale across tenants (`db_name`), not replicas of one file
- Turso-like *primary*: open a named DB, HTTP or Class RPC against it
- Honest latency: in-process HTTP on the writer; Class RPC for workers

### Non-goals

- Embedded-replica / local-first sync (Turso push/pull) — needs a sync engine
- Public arbitrary-SQL over the internet — RPC SQL is trusted workspace only
- Strong sync durability on every write — Volume flush is periodic (~30s) + exit

| File | Role |
|------|------|
| [`sqlite.py`](sqlite.py) | `SqliteDatabase` — writer, Volume, Class RPC, mounts HTTP |
| [`api.py`](api.py) | Notes FastAPI factory (in-process on the writer) |
| [`seed.py`](seed.py) / [`bench.py`](bench.py) | Seed + load tests |
| [`models.py`](models.py) | SQLAlchemy schema (Alembic) |

## Architecture

```text
HTTP  ──► SqliteDatabase(db_name=…).web   ← same container, local sqlite3
Workers ──.remote──► SqliteDatabase
                         hot: /tmp/sqlite/{db}.db
                         durable: Volume /data/{db}.db  (background + exit)
```

`max_containers=1` is **per `db_name`**. Pick the DB with `?db_name=tenant-acme` (Modal Class parameter). Crash between flushes can lose recent writes.

## Quickstart

```bash
uv sync
uv run modal serve sqlite.py
```

```bash
export URL=https://…   # …-sqlitedatabase-web-dev.modal.run

curl "$URL/health?db_name=tenant-acme"
curl -X POST "$URL/notes?db_name=tenant-acme" \
  -H 'content-type: application/json' -d '{"body":"hello"}'
curl "$URL/notes?db_name=tenant-acme"
curl "$URL/notes?db_name=tenant-globex"
```

```python
from sqlite import SqliteDatabase

db = SqliteDatabase(db_name="tenant-acme")
db.execute.remote("INSERT INTO note (body) VALUES (?)", ("hello",))
```

```bash
uv run modal run seed.py
uv run modal run bench.py
```

## Schema

1. Edit `models.py`
2. `uv run alembic revision --autogenerate -m "…"`
3. Redeploy — Alembic runs on `@modal.enter`
