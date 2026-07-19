# ---
# cmd: ["modal", "run", "examples/multi/app.py"]
# ---
#
# Multi-DB smoke: two Sqlites on one App (one Server + Volume each).
# Requires MODAL_PROXY_TOKEN_ID / MODAL_PROXY_TOKEN_SECRET.

from __future__ import annotations

import os

import modal

from sqlite_modal import Sqlite

REGION = os.environ.get("SQLITE_MODAL_REGION", "eu-west")
CLOUD = os.environ.get("SQLITE_MODAL_CLOUD", "aws")
MIN_CONTAINERS = int(os.environ.get("SQLITE_MODAL_MIN_CONTAINERS", "1"))

app = modal.App("example-sqlite-multi")

alpha = Sqlite.from_name("alpha")
alpha.attach(app, region=REGION, cloud=CLOUD, min_containers=MIN_CONTAINERS)

beta = Sqlite.from_name("beta")
beta.attach(app, region=REGION, cloud=CLOUD, min_containers=MIN_CONTAINERS)

DDL = "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)"


@app.local_entrypoint()
def main() -> None:
    for db, label in ((alpha, "alpha"), (beta, "beta")):
        with db:
            db.execute(DDL)
            db.execute("DELETE FROM t")
            db.execute("INSERT INTO t (v) VALUES (?)", (f"hello from {label}",))
            print(label, db.query("SELECT id, v FROM t ORDER BY id"), db.url)
