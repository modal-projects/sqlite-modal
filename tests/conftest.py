"""Shared pytest fixtures."""

from __future__ import annotations

import os

# remote.py builds modal.App at import time from SQLITE_MODAL_NAME.
os.environ.setdefault("SQLITE_MODAL_NAME", "test")
