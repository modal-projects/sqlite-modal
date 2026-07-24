"""Two named DBs (two Modal Apps).

```bash
uv run python examples/multi/app.py
```
"""

from __future__ import annotations

from pathlib import Path

from sqlite_modal import Sqlite

HERE = Path(__file__).resolve().parent


def main() -> None:
    for name, body in (("multi_a", "alpha"), ("multi_b", "beta")):
        db = Sqlite.from_name(
            name,
            create_if_missing=True,
            create_options={"max_containers": 1},
        )
        conn = db.connect(HERE / f".{name}.db")
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, body TEXT)"
            )
            conn.execute("INSERT INTO items (body) VALUES (?)", (body,))
            conn.commit()
            conn.push()
            conn.pull()
            rows = conn.execute("SELECT id, body FROM items ORDER BY id").fetchall()
            print(name, rows)


if __name__ == "__main__":
    main()
