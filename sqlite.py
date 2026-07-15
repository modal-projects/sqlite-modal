# ---
# cmd: ["modal", "serve", "sqlite.py"]
# deploy: true
# ---
#
# One named DB → one writer container (max_containers=1 per db_name).
# Hot file on /tmp; Volume snapshot in the background (~30s) and on exit.
# HTTP mounts in-process (api.create_notes_app). Class RPC is for workers.
# execute / query / executemany: trusted workspace callers only.

import os
import re
import shutil
import sqlite3
import threading
from pathlib import Path

import modal

from api import create_notes_app

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_sync()
    .add_local_python_source("sqlite", "api", "models")
    .add_local_dir("alembic", remote_path="/root/alembic")
    .add_local_file("alembic.ini", remote_path="/root/alembic.ini")
)

volume = modal.Volume.from_name("example-sqlite-rpc", create_if_missing=True)
app = modal.App("example-sqlite-rpc", image=image)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
PERSIST_INTERVAL_S = 30.0
WAL_SUFFIXES = ("-wal", "-shm")


@app.cls(
    volumes={"/data": volume},
    max_containers=1,  # per db_name — many tenants ⇒ many containers
    scaledown_window=5 * 60,
    timeout=5 * 60,
)
class SqliteDatabase:
    db_name: str = modal.parameter()

    @modal.enter()
    def open(self):
        if not NAME_RE.fullmatch(self.db_name):
            raise ValueError(f"invalid db_name {self.db_name!r}")

        self.path = Path("/tmp/sqlite") / f"{self.db_name}.db"
        self.vol_path = Path("/data") / f"{self.db_name}.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._persist_lock = threading.Lock()
        self._stop_persist = threading.Event()

        if self.vol_path.exists():
            shutil.copy2(self.vol_path, self.path)
            for suffix in WAL_SUFFIXES:
                src = Path(f"{self.vol_path}{suffix}")
                if src.exists():
                    shutil.copy2(src, f"{self.path}{suffix}")

        self._migrate()

        self.conn = sqlite3.connect(self.path, timeout=5.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")

        self._persist_thread = threading.Thread(
            target=self._persist_loop, name="sqlite-persist", daemon=True
        )
        self._persist_thread.start()

    def _migrate(self):
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

    def _persist_loop(self):
        while not self._stop_persist.wait(PERSIST_INTERVAL_S):
            try:
                self.flush()
            except Exception:
                pass

    def flush(self):
        """Snapshot hot DB onto the Volume (side connection; safe from the timer thread)."""
        if not self.path.exists():
            return
        with self._persist_lock:
            with sqlite3.connect(self.path, timeout=5.0) as side:
                side.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            shutil.copy2(self.path, self.vol_path)
            for suffix in WAL_SUFFIXES:
                Path(f"{self.vol_path}{suffix}").unlink(missing_ok=True)
            volume.commit()

    @modal.exit()
    def close(self):
        self._stop_persist.set()
        self._persist_thread.join(timeout=5.0)

        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = None

        try:
            self.flush()
        except Exception:
            pass

    @modal.method()
    def execute(self, sql: str, params: tuple = ()) -> dict:
        try:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}

    @modal.method()
    def executemany(self, sql: str, seq_of_params: list) -> dict:
        try:
            cur = self.conn.executemany(sql, seq_of_params)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return {"rowcount": cur.rowcount}

    @modal.method()
    def query(self, sql: str, params: tuple = ()) -> list:
        return [dict(row) for row in self.conn.execute(sql, params)]

    @modal.asgi_app()
    def web(self):
        return create_notes_app(db_name=self.db_name, conn=self.conn)
