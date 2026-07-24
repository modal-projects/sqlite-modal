"""Turso engine pins and Modal Image for the sync remote."""

from __future__ import annotations

import modal

# Pin a known-compatible tursodb ↔ pyturso pair (Tursodal-era sync protocol).
TURSODB_VERSION = "0.6.0"
PYTURSO_VERSION = "0.5.1"

SYNC_PORT = 8080
HOT_DB_PATH = "/tmp/server.db"
VOLUME_MOUNT = "/data"
VOLUME_NAME = "sqlite-modal-data"
APP_PREFIX = "sqlite-modal"
REMOTE_NAME = "SyncServer"
SYNC_PORT_ENV = "SQLITE_MODAL_SYNC_PORT"
DB_NAME_ENV = "SQLITE_MODAL_NAME"

remote_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("curl")
    .pip_install(f"pyturso=={PYTURSO_VERSION}")
    .run_commands(
        "curl --proto '=https' --tlsv1.2 -LsSf "
        f"https://github.com/tursodatabase/turso/releases/download/v{TURSODB_VERSION}/"
        "turso_cli-installer.sh | sh",
        "ln -sf /root/.turso/tursodb /usr/local/bin/tursodb",
        "test -x /usr/local/bin/tursodb",
    )
    .env({"RUST_LOG": "info"})
    .add_local_python_source("sqlite_modal")
)
