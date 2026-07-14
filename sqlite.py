# # SQLite on Modal (Class RPC)
#
# One named DB → one writer container. Callers use Class method RPC; they never
# mount the Volume:
#
# ```python
# db = SqliteDatabase(db_name=f"tenant-{tenant_id}")
# await db.execute.remote.aio("INSERT INTO note (body) VALUES (?)", ("hi",))
# rows = await db.query.remote.aio("SELECT id, body FROM note")
# ```
#
# Hot DB on local disk; hydrate from the Volume on enter, flush on exit.
# Each method opens its own short-lived connection (safe under
# `@modal.concurrent`; WAL + busy_timeout serialize writers).
#
# ```bash
# uv run modal serve api.py
# uv run modal run seed.py
# uv run modal run bench.py
# ```

import os
import re
import shutil
import sqlite3
from pathlib import Path

import modal

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync()
    .add_local_python_source("sqlite", "models")
    .add_local_dir("alembic", remote_path="/root/alembic")
    .add_local_file("alembic.ini", remote_path="/root/alembic.ini")
)

volume = modal.Volume.from_name("example-sqlite-rpc", create_if_missing=True)
app = modal.App("example-sqlite-rpc", image=image)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@app.cls(
    volumes={"/data": volume},
    max_containers=1,
    scaledown_window=5 * 60,
    timeout=5 * 60,
)
@modal.concurrent(max_inputs=64)
class SqliteDatabase:
    db_name: str = modal.parameter()

    @modal.enter()
    def open(self):
        if not NAME_RE.fullmatch(self.db_name):
            raise ValueError(f"invalid db_name {self.db_name!r}")

        self.vol_path = Path("/data") / f"{self.db_name}.db"
        self.path = Path("/tmp/sqlite") / f"{self.db_name}.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.vol_path.parent.mkdir(parents=True, exist_ok=True)

        if self.vol_path.exists():
            shutil.copy2(self.vol_path, self.path)
            for suffix in ("-wal", "-shm"):
                src = Path(f"{self.vol_path}{suffix}")
                if src.exists():
                    shutil.copy2(src, f"{self.path}{suffix}")

        from alembic import command
        from alembic.config import Config

        ini = Path("/root/alembic.ini")
        if not ini.is_file():
            ini = Path(__file__).resolve().parent / "alembic.ini"
        cfg = Config(str(ini))
        url = f"sqlite:///{self.path}"
        os.environ["DATABASE_URL"] = url
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")

        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

    @modal.exit()
    def close(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(self.path, self.vol_path)
        for suffix in ("-wal", "-shm"):
            Path(f"{self.vol_path}{suffix}").unlink(missing_ok=True)
        volume.commit()

    @modal.method()
    def execute(self, sql: str, params: tuple = ()) -> dict:
        with sqlite3.connect(self.path, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                cur = conn.execute(sql, params)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise RuntimeError(f"execute: {e}") from e
            return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}

    @modal.method()
    def executemany(self, sql: str, seq_of_params: list) -> dict:
        with sqlite3.connect(self.path, timeout=5.0) as conn:
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                cur = conn.executemany(sql, seq_of_params)
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                raise RuntimeError(f"executemany: {e}") from e
            return {"rowcount": cur.rowcount}

    @modal.method()
    def query(self, sql: str, params: tuple = ()) -> list:
        with sqlite3.connect(self.path, timeout=5.0) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                cur = conn.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
            except sqlite3.Error as e:
                raise RuntimeError(f"query: {e}") from e
