"""Server lifecycle tests — mocked Popen / Volume."""

from __future__ import annotations

import signal
import subprocess
import threading
from unittest.mock import MagicMock

import pytest

from sqlite_modal.server import Server


def test_stop_sends_sigterm_then_commits() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    volume = MagicMock()

    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._proc = proc
    server._volume = volume

    server.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=Server.CHILD_EXIT_WAIT_S)
    volume.commit.assert_called_once()
    assert server._stopping.is_set()


def test_stop_kills_on_wait_timeout() -> None:
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="uvicorn", timeout=Server.CHILD_EXIT_WAIT_S),
        None,
    ]
    volume = MagicMock()

    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._proc = proc
    server._volume = volume

    server.stop()

    proc.send_signal.assert_called_once_with(signal.SIGTERM)
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2
    volume.commit.assert_called_once()


def test_stop_swallows_commit_error() -> None:
    proc = MagicMock()
    proc.poll.return_value = 0
    volume = MagicMock()
    volume.commit.side_effect = RuntimeError("commit failed")

    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._proc = proc
    server._volume = volume

    server.stop()
    volume.commit.assert_called_once()


def test_wait_until_healthy_raises_if_child_exits() -> None:
    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._proc = MagicMock()
    server._proc.poll.return_value = 1
    server._proc.returncode = 1
    with pytest.raises(RuntimeError, match="exited before healthy"):
        server.HEALTH_WAIT_S = 0.2
        server._wait_until_healthy()


def test_wait_until_healthy_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._proc = MagicMock()
    server._proc.poll.return_value = None

    class FakeResp:
        status = 200

        def __enter__(self) -> FakeResp:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

    monkeypatch.setattr(
        "sqlite_modal.server.urllib.request.urlopen",
        lambda *_a, **_k: FakeResp(),
    )
    server._wait_until_healthy()


def test_watch_child_logs_info_on_intentional_stop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    server = Server.__new__(Server)
    server._stopping = threading.Event()
    server._stopping.set()
    server._proc = MagicMock()
    server._proc.wait.return_value = -15

    with caplog.at_level(logging.INFO, logger="sqlite_modal.server"):
        server._watch_child()
    assert any("after stop" in r.message for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_child_exit_wait_under_modal_budget() -> None:
    assert Server.CHILD_EXIT_WAIT_S < 30
    assert Server.CHILD_EXIT_WAIT_S + 5 < 30
