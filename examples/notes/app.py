"""Notes smoke: Turso Sync on Modal.

```bash
uv run python examples/notes/app.py
```
"""

from __future__ import annotations

from pathlib import Path

from sqlite_modal import Sqlite

LOCAL_DB = Path(__file__).resolve().parent / ".notes.db"


def main() -> None:
    db = Sqlite.from_name(
        "notes_demo",
        create_if_missing=True,
        create_options={"max_containers": 1},
    )
    with db.connect(LOCAL_DB) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, body TEXT)"
        )
        conn.execute("INSERT INTO notes (body) VALUES (?)", ("hello from modal",))
        conn.commit()
        conn.push()
        conn.pull()
        rows = conn.execute("SELECT id, body FROM notes ORDER BY id").fetchall()
        print(rows)


if __name__ == "__main__":
    main()
