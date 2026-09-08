"""Turso Sync remote as a Modal Server (used by ``Sqlite.from_name``)."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import BinaryIO, TypedDict

import modal

from sqlite_modal.turso import (
    APP_PREFIX,
    DB_NAME_ENV,
    HOT_DB_PATH,
    SYNC_PORT,
    SYNC_PORT_ENV,
    VOLUME_MOUNT,
    remote_image,
    volume_name,
)

logger = logging.getLogger("sqlite_modal.remote")

STDERR_PATH = Path("/tmp/tursodb.stderr")


class CreateOptions(TypedDict, total=False):
    """``@app.server`` kwargs for ``Sqlite.from_name(..., create_options=)``."""

    port: int
    image: modal.Image
    cpu: float | tuple[float, float]
    memory: int | tuple[int, int]
    ephemeral_disk: int
    gpu: str | list[str]
    secrets: Collection[modal.Secret]
    volumes: Mapping[str | PurePosixPath, modal.Volume | modal.CloudBucketMount]
    env: Mapping[str, str | None]
    proxy: modal.Proxy
    cloud: str
    nonpreemptible: bool
    compute_region: str | Sequence[str]
    routing_region: str
    target_concurrency: int
    min_containers: int
    max_containers: int
    buffer_containers: int
    scaleup_window: int
    scaledown_window: int
    startup_timeout: int
    exit_grace_period: int
    h2_enabled: bool
    enable_memory_snapshot: bool
    experimental_options: dict[str, object]
    i6pn: bool


class ServerStore:
    """Hot ephemeral ``server.db*`` ↔ cold Volume directory."""

    def __init__(self, hot: Path, cold_dir: Path) -> None:
        self.hot = hot
        self.cold_dir = cold_dir

    def restore(self) -> None:
        self.hot.parent.mkdir(parents=True, exist_ok=True)
        if not self.cold_dir.is_dir():
            return
        for src in self.cold_dir.glob("server.db*"):
            shutil.copy2(src, self.hot.parent / src.name)

    def save(self) -> None:
        if not self.hot.is_file():
            return
        self.cold_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.cold_dir.glob("server.db*"):
            stale.unlink()
        for src in self.hot.parent.glob("server.db*"):
            shutil.copy2(src, self.cold_dir / src.name)


class SyncServer:
    """Module-level ``tursodb --sync-server`` lifecycle for ``@app.server``."""

    proc: subprocess.Popen[bytes] | None
    log: BinaryIO | None
    port: int
    db_name: str
    store: ServerStore

    @modal.enter()
    def start(self) -> None:
        self.proc = None
        self.log = None
        self.port = int(os.environ.get(SYNC_PORT_ENV, str(SYNC_PORT)))
        self.db_name = os.environ[DB_NAME_ENV]
        self.store = ServerStore(
            Path(HOT_DB_PATH),
            Path(VOLUME_MOUNT),
        )
        self.store.restore()
        self.spawn()

    @modal.exit()
    def stop(self) -> None:
        self.stop_process()
        try:
            self.store.save()
            modal.Volume.from_name(volume_name(self.db_name)).commit()
        except Exception:
            logger.exception("Volume save on exit failed for %s", self.db_name)

    def spawn(self) -> None:
        log_file: BinaryIO = STDERR_PATH.open("wb")
        self.log = log_file
        self.proc = subprocess.Popen(
            [
                "tursodb",
                HOT_DB_PATH,
                "--sync-server",
                f"0.0.0.0:{self.port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=log_file,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"tursodb exited: {self.stderr_text()}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"tursodb not ready: {self.stderr_text()}")

    def stop_process(self) -> None:
        proc = self.proc
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        self.proc = None

        log_file = self.log
        if log_file is not None and not log_file.closed:
            log_file.close()
        self.log = None

    def stderr_text(self) -> str:
        if not STDERR_PATH.is_file():
            return ""
        return STDERR_PATH.read_text(encoding="utf-8", errors="replace")


class RemoteApp:
    """Deploys ``sqlite-modal-{name}`` wrapping module-level ``SyncServer``."""

    @classmethod
    def deploy(
        cls,
        name: str,
        *,
        create_options: CreateOptions | None = None,
        environment_name: str | None = None,
        client: modal.Client | None = None,
    ) -> modal.App:
        opts: CreateOptions = create_options or {}
        data_volume = modal.Volume.from_name(
            volume_name(name),
            create_if_missing=True,
            environment_name=environment_name,
            client=client,
        )
        port = opts.get("port", SYNC_PORT)
        volumes: dict[str | PurePosixPath, modal.Volume | modal.CloudBucketMount] = {
            **dict(opts.get("volumes", {})),
            VOLUME_MOUNT: data_volume,
        }
        env: dict[str, str | None] = dict(opts.get("env", {}))
        env[DB_NAME_ENV] = name
        env[SYNC_PORT_ENV] = str(port)

        app = modal.App(f"{APP_PREFIX}-{name}")
        app.server(
            image=opts.get("image", remote_image),
            env=env,
            secrets=opts.get("secrets"),
            gpu=opts.get("gpu"),
            volumes=volumes,
            cpu=opts.get("cpu"),
            memory=opts.get("memory"),
            ephemeral_disk=opts.get("ephemeral_disk"),
            target_concurrency=opts.get("target_concurrency"),
            min_containers=opts.get("min_containers"),
            max_containers=opts.get("max_containers"),
            buffer_containers=opts.get("buffer_containers"),
            scaleup_window=opts.get("scaleup_window"),
            scaledown_window=opts.get("scaledown_window"),
            startup_timeout=opts.get("startup_timeout", 120),
            port=port,
            unauthenticated=True,
            h2_enabled=opts.get("h2_enabled", False),
            exit_grace_period=opts.get("exit_grace_period", 0),
            routing_region=opts.get("routing_region", "us-east"),
            compute_region=opts.get("compute_region"),
            cloud=opts.get("cloud"),
            nonpreemptible=opts.get("nonpreemptible", False),
            proxy=opts.get("proxy"),
            i6pn=opts.get("i6pn"),
            enable_memory_snapshot=opts.get("enable_memory_snapshot", False),
            experimental_options=opts.get("experimental_options"),
        )(SyncServer)
        with modal.enable_output():
            app.deploy(environment_name=environment_name, client=client)
        return app
