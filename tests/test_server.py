"""Server lifecycle tests — mocked Popen / Volume."""

from __future__ import annotations

import signal
import subprocess
from unittest.mock import MagicMock

import pytest

from sqlite_modal.server import Server


def test_stop_sends_sigterm_then_commits(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    volume = MagicMock()

    server = Server.__new__(Server)
    server._proc = proc
    server._volume = volume

    server.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=30)
    volume.commit.assert_called_once()


def test_stop_kills_on_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="uvicorn", timeout=30),
        None,
    ]
    volume = MagicMock()

    server = Server.__new__(Server)
    server._proc = proc
    server._volume = volume

    server.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2
    volume.commit.assert_called_once()


def test_stop_swallows_commit_error(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = MagicMock()
    proc.poll.return_value = 0
    volume = MagicMock()
    volume.commit.side_effect = RuntimeError("commit failed")

    server = Server.__new__(Server)
    server._proc = proc
    server._volume = volume

    server.stop()  # must not raise
    volume.commit.assert_called_once()
