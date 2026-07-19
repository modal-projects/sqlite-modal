"""Modal runtime — Popen uvicorn, readiness, exit commit.

Registered only by ``Sqlite.attach`` — not part of the public API.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import modal

logger = logging.getLogger("sqlite_modal.server")


class Server:
    """Start uvicorn on ``HTTP_PORT``; SQLite lives in that process."""

    HTTP_PORT = 8000
    # Leave headroom inside Modal's ~30s exit-handler window for volume.commit.
    CHILD_EXIT_WAIT_S = 10
    HEALTH_POLL_INTERVAL_S = 0.05
    HEALTH_WAIT_S = 90.0

    # Keep in sync with ``[project.optional-dependencies].server`` in pyproject.toml.
    PIP_PACKAGES: tuple[str, ...] = (
        "fastapi[standard]>=0.139.0,<1",
        "uvicorn>=0.34.0,<1",
    )

    def __init__(self) -> None:
        self._stopping = threading.Event()

    @classmethod
    def for_name(cls, name: str) -> type[Server]:
        """Subclass uniquely named for Modal ``app.server`` registration."""
        return type(f"SqliteServer_{name}", (cls,), {})

    @modal.enter()
    def start(self) -> None:
        self._stopping = threading.Event()
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
                str(self.HTTP_PORT),
                "--log-level",
                "warning",
            ],
        )
        self._wait_until_healthy()
        threading.Thread(
            target=self._watch_child,
            name=f"sqlite-modal-watch-{name}",
            daemon=True,
        ).start()

    def _wait_until_healthy(self) -> None:
        url = f"http://127.0.0.1:{self.HTTP_PORT}/health"
        deadline = time.monotonic() + self.HEALTH_WAIT_S
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"uvicorn exited before healthy (code={self._proc.returncode})"
                )
            try:
                with urllib.request.urlopen(url, timeout=1.0) as resp:
                    if resp.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(self.HEALTH_POLL_INTERVAL_S)
        raise RuntimeError(
            f"uvicorn health check timed out after {self.HEALTH_WAIT_S:.0f}s"
        )

    def _watch_child(self) -> None:
        code = self._proc.wait()
        if self._stopping.is_set():
            logger.info("uvicorn child exited after stop (code=%s)", code)
            return
        logger.error(
            "uvicorn child exited unexpectedly (code=%s); container is unhealthy",
            code,
        )

    @modal.exit()
    def stop(self) -> None:
        self._stopping.set()
        if self._proc.poll() is None:
            self._proc.send_signal(signal.SIGTERM)
            try:
                self._proc.wait(timeout=self.CHILD_EXIT_WAIT_S)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
        try:
            self._volume.commit()
        except Exception as exc:
            logger.exception(
                "sqlite volume commit on exit (data may be uncommitted): %s",
                exc,
            )
