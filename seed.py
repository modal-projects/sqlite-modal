"""Seed demo notes into tenant DBs via Class RPC.

    uv run modal run seed.py
    uv run modal run seed.py --tenants acme,globex
"""

from sqlite import SqliteDatabase, app


@app.local_entrypoint()
def seed(tenants: str = "acme,globex"):
    for tenant_id in (t.strip() for t in tenants.split(",") if t.strip()):
        db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
        db.execute.remote("INSERT INTO note (body) VALUES (?)", (f"hello from {tenant_id}",))
        rows = db.query.remote("SELECT id, body FROM note ORDER BY id")
        print(tenant_id, rows)
