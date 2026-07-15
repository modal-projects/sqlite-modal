# Distributed SQLite on Modal

Multi-tenant SQLite on [Modal](https://modal.com): one exclusive writer container per named database, durable on a Volume. Callers use **Class RPC** (`.remote`).

Copyable architecture example — not a managed database product.

## Layout

| File | Role |
|------|------|
| [`sqlite.py`](sqlite.py) | `SqliteDatabase` — Volume writer + Class RPC |
| [`api.py`](api.py) | Example Notes HTTP (scales out; RPCs into the writer) |
| [`models.py`](models.py) | SQLAlchemy schema (Alembic) |
| [`seed.py`](seed.py) / [`bench.py`](bench.py) | Seed + load tests |

## Architecture

```text
HTTP  ──► web() ──.remote──► SqliteDatabase(db_name=…)   max_containers=1
Workers ──────────.remote──►┘
                                   hot: /tmp/sqlite/{db}.db
                                   durable: Volume /data/{db}.db
```

- Scale across tenants: many `db_name`s → many writers.
- HTTP is an optional demo surface; workers should call Class RPC directly.
- Writer, HTTP, and bench runners share `REGION` / `ROUTING_REGION` in [`sqlite.py`](sqlite.py) so Class RPC stays in-region.
- Volume flush is ~every 30s and on exit. Crash between flushes can lose recent writes.
- `execute` / `query` / `executemany` are for **trusted workspace callers** (arbitrary SQL).

### Relation to Turso / Archil

| Idea | Turso | Archil | This example |
|------|-------|--------|--------------|
| DB-per-tenant | Named cloud DBs | SQLite files on disk | `db_name` Class parameter |
| Exclusive writer | Cloud primary | Mount/`checkout` ownership | `max_containers=1` per name |
| Hot + durable | Engine + cloud | Cache + S3 sync | `/tmp` + Volume flush |
| Access API | Client / URL | Local `sqlite3` on mount | Class RPC `.remote` |
| Replicas / sync | Embedded replicas, Sync | N/A (filesystem) | Not implemented |

We implement a **Modal-native primary** (Turso-like open-named-DB; Archil-like exclusive ownership + background durability). We do not implement Turso embedded-replica / push-pull sync.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- A [Modal](https://modal.com) account (`modal setup`)

## Quickstart

```bash
uv sync
uv run modal serve api.py
```

```bash
export URL=https://…-web-dev.modal.run

curl "$URL/health"
curl -X POST "$URL/t/acme/notes" -H 'content-type: application/json' \
  -d '{"body":"hello"}'
curl "$URL/t/acme/notes"
curl "$URL/t/globex/notes"
```

Workers:

```python
from sqlite import SqliteDatabase

db = SqliteDatabase(db_name="tenant-acme")
db.execute.remote("INSERT INTO note (body) VALUES (?)", ("hello",))
db.query.remote("SELECT id, body FROM note ORDER BY id LIMIT 50")
```

```bash
uv run modal run seed.py
uv run modal run bench.py   # bench_results.json + docs/charts/
```

## Schema

1. Edit [`models.py`](models.py)
2. `uv run alembic revision --autogenerate -m "…"`
3. Redeploy — Alembic runs on `@modal.enter`

## Benchmarks

`uv run modal run bench.py` — Class RPC (`.remote.aio`) against `SqliteDatabase`, warm containers, ~250B payloads, concurrency 64, `region` / `routing_region` = `eu-west`.

Latest run (see `docs/charts/`):

| Scenario | Result |
|----------|--------|
| Single-row writes | ~137 ops/s · p50 **378 ms** · p95 737 ms |
| Point reads | ~158 ops/s · p50 **400 ms** · p95 459 ms |
| `executemany` (200-row batches) | **~3773 rows/s** |
| Two tenants in parallel | **~339 combined ops/s** |

### Throughput

![Class RPC throughput](docs/charts/throughput.png)

### Latency (p50)

![Class RPC latency](docs/charts/latency.png)

### Batching

![Batching amortizes RPC](docs/charts/batching.png)

### Multi-tenant scale-out

![Two tenants in parallel](docs/charts/multi_tenant.png)

Chatty single-row Class RPC is ~RTT-bound (transport, not SQLite). Prefer `executemany` for bulk writes; scale out with more `db_name`s.

## Gotchas

| Topic | Detail |
|-------|--------|
| Scaling | More `db_name`s, not more writers on one file. |
| Latency | Chatty `.remote` is transport-bound; batch when you can. |
| Durability | Local `/tmp` first; Volume snapshots periodically. |
| HTTP | Adds a hop (HTTP → RPC → SQLite). Prefer direct `.remote` for workers. |
