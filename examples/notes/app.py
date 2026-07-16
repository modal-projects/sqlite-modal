# ---
# cmd: ["modal", "serve", "examples/notes/app.py"]
# deploy: true
# ---
#
# Demo: single Sqlite (from_name → attach → SQL).
# Requires MODAL_PROXY_TOKEN_ID / MODAL_PROXY_TOKEN_SECRET
# (RBAC: modal workspace proxy-tokens allow <id> main).

from __future__ import annotations

import modal

from examples.notes.schema import NOTE_DDL
from sqlite_modal import Sqlite

REGION = "eu-west"
CLOUD = "aws"

app = modal.App("example-sqlite")

db = Sqlite.from_name("notes")
db.attach(app, region=REGION, cloud=CLOUD, min_containers=1)


@app.local_entrypoint()
def main() -> None:
    """Smoke: schema + executemany insert + query + flush."""
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
