"""Local Turso Sync replica bound to a named Modal Sqlite remote."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

from turso.sync import ConnectionSync

from sqlite_modal import Sqlite

NOTE_DDL = (
    "CREATE TABLE IF NOT EXISTS note "
    "(id INTEGER PRIMARY KEY, body TEXT NOT NULL)"
)


class LocalReplica:
    """One local DB file synced to a ``Sqlite`` remote.

    Readiness is Modal Server HTTP semantics: a warm Server answers with a
    non-503 status (tursodb often returns 404 on bare GET); scale-to-zero
    answers 503 until a container is up.
    """

    def __init__(self, remote: Sqlite, path: Path) -> None:
        self.remote = remote
        self.path = path

    def clear(self) -> None:
        parent = self.path.parent
        parent.mkdir(parents=True, exist_ok=True)
        for p in parent.glob(f"{self.path.name}*"):
            p.unlink()

    def wait_ready(self, *, timeout_s: float = 120.0) -> None:
        url = self.remote.remote_url
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(url, timeout=2.0)
                return
            except urllib.error.HTTPError as exc:
                if exc.code != 503:
                    return
            except urllib.error.URLError:
                pass
            time.sleep(0.5)
        raise TimeoutError(
            f"Sqlite {self.remote.name!r} Server not ready within "
            f"{timeout_s:.0f}s at {url}"
        )

    def open(self) -> ConnectionSync:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.wait_ready()
        return self.remote.connect(self.path)

    def reset_schema(self, conn: ConnectionSync) -> None:
        conn.execute(NOTE_DDL)
        conn.execute("DELETE FROM note")
        conn.commit()

    def bootstrap(self) -> ConnectionSync:
        """Clear local files, open, create empty ``note`` table, push."""
        self.clear()
        conn = self.open()
        self.reset_schema(conn)
        conn.push()
        return conn
