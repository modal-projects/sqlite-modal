"""Turso engine pins and Modal Image for the sync remote."""

from __future__ import annotations

import modal

# Pin a known-compatible tursodb and pyturso pair for the sync protocol.
TURSODB_VERSION = "0.6.0"
PYTURSO_VERSION = "0.5.1"

SYNC_PORT = 8080
HOT_DB_PATH = "/tmp/server.db"
VOLUME_MOUNT = "/data"
APP_PREFIX = "sqlite-modal"
REMOTE_NAME = "SyncServer"
SYNC_PORT_ENV = "SQLITE_MODAL_SYNC_PORT"
DB_NAME_ENV = "SQLITE_MODAL_NAME"

TURSODB_LINUX_X64 = (
    f"https://github.com/tursodatabase/turso/releases/download/v{TURSODB_VERSION}/"
    "turso_cli-x86_64-unknown-linux-gnu.tar.xz"
)
TURSODB_LINUX_X64_SHA256 = (
    "c9a05e491f95f37406921b3497f65c711663a27fcdc419c7f9474137bd1d512d"
)
TURSODB_LINUX_X64_DIR = "turso_cli-x86_64-unknown-linux-gnu"


def volume_name(db_name: str) -> str:
    return f"{APP_PREFIX}-{db_name}-data"


remote_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl", "xz-utils")
    .pip_install(f"pyturso=={PYTURSO_VERSION}")
    .run_commands(
        "curl --proto '=https' --tlsv1.2 -fsSL "
        f"-o /tmp/turso.tar.xz {TURSODB_LINUX_X64} && "
        f"echo '{TURSODB_LINUX_X64_SHA256}  /tmp/turso.tar.xz' | sha256sum -c - && "
        "tar -xJf /tmp/turso.tar.xz -C /tmp && "
        f"install -m 0755 /tmp/{TURSODB_LINUX_X64_DIR}/tursodb /usr/local/bin/tursodb && "
        "test -x /usr/local/bin/tursodb && "
        f"rm -rf /tmp/turso.tar.xz /tmp/{TURSODB_LINUX_X64_DIR}",
    )
    .env({"RUST_LOG": "info"})
    .add_local_python_source("sqlite_modal")
)
