# ---
# cmd: ["modal", "serve", "examples/notes/app.py"]
# deploy: true
# ---
#
# Demo: single Sqlite (from_name → attach → SQL).
# Requires MODAL_PROXY_TOKEN_ID / MODAL_PROXY_TOKEN_SECRET
# (RBAC: modal workspace proxy-tokens allow <id> main).

from __future__ import annotations

import os

import modal

from examples.notes.schema import NOTE_DDL
from sqlite_modal import Sqlite

REGION = os.environ.get("SQLITE_MODAL_REGION", "eu-west")
CLOUD = os.environ.get("SQLITE_MODAL_CLOUD", "aws")
MIN_CONTAINERS = int(os.environ.get("SQLITE_MODAL_MIN_CONTAINERS", "1"))

app = modal.App("example-sqlite")

db = Sqlite.from_name("notes")
db.attach(app, region=REGION, cloud=CLOUD, min_containers=MIN_CONTAINERS)


@app.local_entrypoint()
def main() -> None:
    """Smoke: schema + executemany insert + query + flush."""
    with db:
        db.execute(NOTE_DDL)
        db.execute("DELETE FROM note")
        db.executemany(
            "INSERT INTO note (body) VALUES (?)",
            [
                ["hello from notes"],
                ["second row"],
                ["third row"],
            ],
        )
        print(db.query("SELECT id, body FROM note ORDER BY id"))
        print("url", db.url)
        db.flush()
