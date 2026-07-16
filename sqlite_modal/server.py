"""Private Modal Server: Popen uvicorn for ``sqlite_modal.api``.

Registered only by ``Sqlite.attach`` — not part of the public API.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys

import modal

HTTP_PORT = 8000

logger = logging.getLogger("sqlite_modal.server")


class Server:
    """Start uvicorn on ``HTTP_PORT``; SQLite lives in that process."""

    @classmethod
    def for_name(cls, name: str) -> type[Server]:
        """Subclass uniquely named for Modal ``app.server`` registration."""
        return type(f"SqliteServer_{name}", (cls,), {})

    @modal.enter()
    def start(self) -> None:
        name = os.environ["SQLITE_MODAL_NAME"]
        self._volume = modal.Volume.from_name(f"{name}-data")
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "sqlite_modal.api:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(HTTP_PORT),
                "--log-level",
                "warning",
            ],
        )

    @modal.exit()
    def stop(self) -> None:
        if self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        try:
            self._volume.commit()
        except Exception as exc:
            logger.exception("sqlite volume commit on exit: %s", exc)
