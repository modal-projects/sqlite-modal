"""Client transport tests — no Modal runtime."""

from __future__ import annotations

import json
import os
import time
from typing import TypedDict, cast
from unittest.mock import MagicMock

import httpx
import modal
import pytest

from sqlite_modal import (
    AlreadyAttachedError,
    AuthError,
    ConfigError,
    InvalidNameError,
    NotAttachedError,
    ServiceError,
    SqlError,
    Sqlite,
)
from sqlite_modal import client as client_mod
from sqlite_modal.server import Server


@pytest.fixture
def db() -> Sqlite:
    instance = Sqlite.from_name("test_db")
    instance._server = MagicMock()
    instance._server.get_url.return_value = "https://example.modal.run"
    instance._attached_app = MagicMock()
    return instance


@pytest.fixture
def proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODAL_PROXY_TOKEN_ID", "wk-test")
    monkeypatch.setenv("MODAL_PROXY_TOKEN_SECRET", "ws-test")


def _install_transport(db: Sqlite, handler: httpx.MockTransport) -> None:
    db._http = httpx.Client(transport=handler, timeout=60.0)


class AttachCall(TypedDict):
    serialized: bool | None
    cls_name: str
    env: dict[str, str] | None
    exit_grace_period: int | None


def _mock_attach(
    monkeypatch: pytest.MonkeyPatch, app: modal.App
) -> list[AttachCall]:
    """Stub Volume + app.server; return list of registration calls."""
    calls: list[AttachCall] = []

    def fake_volume_from_name(
        name: str, *, create_if_missing: bool = False
    ) -> modal.Volume:
        return cast(modal.Volume, MagicMock(name=name))

    def fake_server(**kwargs: object) -> object:
        def decorate(cls: type) -> MagicMock:
            env = kwargs.get("env")
            calls.append(
                {
                    "serialized": cast(bool | None, kwargs.get("serialized")),
                    "cls_name": cls.__name__,
                    "env": cast(dict[str, str] | None, env),
                    "exit_grace_period": cast(
                        int | None, kwargs.get("exit_grace_period")
                    ),
                }
            )
            return MagicMock()

        return decorate

    monkeypatch.setattr(modal.Volume, "from_name", fake_volume_from_name)
    monkeypatch.setattr(app, "server", fake_server)
    return calls


def test_from_name_rejects_invalid() -> None:
    with pytest.raises(InvalidNameError, match="invalid Sqlite name"):
        Sqlite.from_name("bad name!")
    with pytest.raises(InvalidNameError, match="invalid Sqlite name"):
        Sqlite.from_name("bad-name")
    with pytest.raises(InvalidNameError, match="invalid Sqlite name"):
        Sqlite.from_name("1x")


def test_config_rejects_bad_timeout() -> None:
    with pytest.raises(ConfigError, match="timeout"):
        Sqlite.from_name("ok", timeout=0)


def test_repr_close_and_context(db: Sqlite) -> None:
    assert "test_db" in repr(db)
    assert "attached=True" in repr(db)
    db._http = httpx.Client()
    db.close()
    assert db._http is None
    db.close()  # idempotent

    with Sqlite.from_name("ctx") as ctx:
        ctx._http = httpx.Client()
    assert ctx._http is None


def test_server_for_name() -> None:
    cls = Server.for_name("orders")
    assert cls.__name__ == "SqliteServer_orders"
    assert issubclass(cls, Server)


def test_server_pip_packages_nonempty() -> None:
    assert any("fastapi" in pkg for pkg in Server.PIP_PACKAGES)
    assert any("uvicorn" in pkg for pkg in Server.PIP_PACKAGES)


def test_attach_allows_multiple_dbs(monkeypatch: pytest.MonkeyPatch) -> None:
    app = modal.App("test-multi")
    calls = _mock_attach(monkeypatch, app)
    a = Sqlite.from_name("alpha")
    b = Sqlite.from_name("beta")
    a.attach(app, region="eu-west", cloud="aws")
    b.attach(app, region="eu-west", cloud="aws")
    assert len(calls) == 2
    assert calls[0]["serialized"] is True
    assert calls[1]["serialized"] is True
    assert calls[0]["cls_name"] == "SqliteServer_alpha"
    assert calls[1]["cls_name"] == "SqliteServer_beta"
    assert calls[0]["exit_grace_period"] == 15
    assert client_mod._attached_names[app] == {"alpha", "beta"}


def test_attach_rejects_duplicate_name(monkeypatch: pytest.MonkeyPatch) -> None:
    app = modal.App("test-dup")
    _mock_attach(monkeypatch, app)
    a = Sqlite.from_name("shared")
    b = Sqlite.from_name("shared")
    a.attach(app, region="eu-west", cloud="aws")
    with pytest.raises(AlreadyAttachedError, match="already has Sqlite 'shared'"):
        b.attach(app, region="eu-west", cloud="aws")


def test_attach_rejects_second_call_same_app() -> None:
    app = modal.App("test-reattach")
    db = Sqlite.from_name("only")
    db._attached_app = app
    with pytest.raises(AlreadyAttachedError, match="already attached"):
        db.attach(app, region="eu-west", cloud="aws")


def test_attach_rejects_bad_min_containers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = modal.App("test-min")
    _mock_attach(monkeypatch, app)
    db = Sqlite.from_name("x")
    with pytest.raises(ConfigError, match="min_containers"):
        db.attach(app, region="eu-west", cloud="aws", min_containers=2)


def test_url_requires_attach() -> None:
    db = Sqlite.from_name("x")
    with pytest.raises(NotAttachedError, match="not attached"):
        _ = db.url


def test_proxy_headers_require_env(db: Sqlite) -> None:
    os.environ.pop("MODAL_PROXY_TOKEN_ID", None)
    os.environ.pop("MODAL_PROXY_TOKEN_SECRET", None)
    db._proxy_headers_cache = None
    with pytest.raises(AuthError, match="proxy tokens"):
        db._proxy_headers()


def test_execute_encodes_params(db: Sqlite, proxy_env: None) -> None:
    seen: list[tuple[str, dict[str, object], dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = cast(dict[str, object], json.loads(request.content.decode()))
        seen.append((str(request.url), body, dict(request.headers)))
        return httpx.Response(200, json={"rowcount": 1, "lastrowid": 7})

    _install_transport(db, httpx.MockTransport(handler))
    out = db.execute("INSERT INTO t (v) VALUES (?)", ("hello",))
    assert out == {"rowcount": 1, "lastrowid": 7}
    assert seen[0][0] == "https://example.modal.run/v1/execute"
    assert seen[0][1] == {
        "sql": "INSERT INTO t (v) VALUES (?)",
        "params": ["hello"],
    }
    assert seen[0][2]["modal-key"] == "wk-test"


def test_query_returns_rows(db: Sqlite, proxy_env: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rows": [{"id": 1, "v": "x"}]})

    _install_transport(db, httpx.MockTransport(handler))
    assert db.query("SELECT id, v FROM t") == [{"id": 1, "v": "x"}]


def test_batch_encodes_ops(db: Sqlite, proxy_env: None) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(cast(dict[str, object], json.loads(request.content.decode())))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"rowcount": 2, "lastrowid": 2},
                    {"rows": [{"n": 2}]},
                ]
            },
        )

    _install_transport(db, httpx.MockTransport(handler))
    out = db.batch(
        [
            {
                "type": "execute",
                "sql": "INSERT INTO t (v) VALUES (?)",
                "params_seq": [["a"], ["b"]],
            },
            {"type": "query", "sql": "SELECT COUNT(*) AS n FROM t", "params": []},
        ]
    )
    assert len(cast(list[object], seen[0]["ops"])) == 2
    assert out[0] == {"rowcount": 2, "lastrowid": 2}
    assert out[1] == {"rows": [{"n": 2}]}


def test_executemany_posts_batch(db: Sqlite, proxy_env: None) -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/v1/batch")
        seen.append(cast(dict[str, object], json.loads(request.content.decode())))
        return httpx.Response(
            200, json={"results": [{"rowcount": 2, "lastrowid": 2}]}
        )

    _install_transport(db, httpx.MockTransport(handler))
    out = db.executemany(
        "INSERT INTO t (v) VALUES (?)",
        [["a"], ["b"]],
    )
    assert out == {"rowcount": 2, "lastrowid": 2}
    assert seen[0]["ops"] == [
        {
            "type": "execute",
            "sql": "INSERT INTO t (v) VALUES (?)",
            "params_seq": [["a"], ["b"]],
        }
    ]


def test_executemany_empty_skips_http(db: Sqlite, proxy_env: None) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500)

    _install_transport(db, httpx.MockTransport(handler))
    assert db.executemany("INSERT INTO t (v) VALUES (?)", []) == {
        "rowcount": 0,
        "lastrowid": 0,
    }
    assert calls["n"] == 0


def test_http_4xx_raises_sql_error(db: Sqlite, proxy_env: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "no such table: t"})

    _install_transport(db, httpx.MockTransport(handler))
    with pytest.raises(SqlError, match="no such table") as info:
        db.execute("INSERT INTO t (v) VALUES (?)", ("x",))
    assert info.value.status_code == 400


def test_http_401_raises_auth_error(db: Sqlite, proxy_env: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    _install_transport(db, httpx.MockTransport(handler))
    with pytest.raises(AuthError, match="unauthorized"):
        db.execute("INSERT INTO t (v) VALUES (?)", ("x",))


def test_http_413_raises_service_error(db: Sqlite, proxy_env: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(413, json={"error": "request body too large"})

    _install_transport(db, httpx.MockTransport(handler))
    with pytest.raises(ServiceError, match="413"):
        db.execute("INSERT INTO t (v) VALUES (?)", ("x",))


def test_http_5xx_raises_service_error(db: Sqlite, proxy_env: None) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal error"})

    _install_transport(db, httpx.MockTransport(handler))
    with pytest.raises(ServiceError, match="internal error"):
        db.execute("INSERT INTO t (v) VALUES (?)", ("x",))


def test_retries_503_then_ok(
    db: Sqlite, proxy_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"rows": [{"ok": 1}]})

    _install_transport(db, httpx.MockTransport(handler))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert db.query("SELECT 1 AS ok") == [{"ok": 1}]
    assert calls["n"] == 3


def test_mutate_retries_connect_error(
    db: Sqlite, proxy_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"rowcount": 1, "lastrowid": 1})

    _install_transport(db, httpx.MockTransport(handler))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert db.execute("INSERT INTO t (v) VALUES (?)", ("x",)) == {
        "rowcount": 1,
        "lastrowid": 1,
    }
    assert calls["n"] == 2


def test_mutate_does_not_retry_read_timeout(
    db: Sqlite, proxy_env: None
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    _install_transport(db, httpx.MockTransport(handler))
    with pytest.raises(ServiceError, match="transport error after send"):
        db.execute("INSERT INTO t (v) VALUES (?)", ("x",))
    assert calls["n"] == 1


def test_query_retries_read_timeout(
    db: Sqlite, proxy_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"rows": [{"ok": 1}]})

    _install_transport(db, httpx.MockTransport(handler))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert db.query("SELECT 1 AS ok") == [{"ok": 1}]
    assert calls["n"] == 2


def test_flush_posts_empty_body(db: Sqlite, proxy_env: None) -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content)
        return httpx.Response(200, json={})

    _install_transport(db, httpx.MockTransport(handler))
    db.flush()
    assert seen[0] in (b"{}", b"null")
