"""FastAPI API tests via TestClient."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import modal
import pytest
from fastapi.testclient import TestClient

from sqlite_modal import api as api_mod


def test_health(api_client: TestClient) -> None:
    r = api_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_execute_query(api_client: TestClient) -> None:
    api_client.post(
        "/v1/execute",
        json={
            "sql": "CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT NOT NULL)",
            "params": [],
        },
    ).raise_for_status()
    api_client.post(
        "/v1/execute",
        json={"sql": "INSERT INTO note (body) VALUES (?)", "params": ["hi"]},
    ).raise_for_status()
    r = api_client.post(
        "/v1/query",
        json={"sql": "SELECT body FROM note", "params": []},
    )
    assert r.status_code == 200
    assert r.json()["rows"] == [{"body": "hi"}]


def test_batch_executemany(api_client: TestClient) -> None:
    api_client.post(
        "/v1/execute",
        json={
            "sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)",
            "params": [],
        },
    ).raise_for_status()
    r = api_client.post(
        "/v1/batch",
        json={
            "ops": [
                {
                    "type": "execute",
                    "sql": "INSERT INTO t (v) VALUES (?)",
                    "params_seq": [["a"], ["b"], ["c"]],
                },
                {"type": "query", "sql": "SELECT COUNT(*) AS n FROM t", "params": []},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["rowcount"] == 3
    assert body["results"][1]["rows"] == [{"n": 3}]


def test_batch_rollback(api_client: TestClient) -> None:
    api_client.post(
        "/v1/execute",
        json={
            "sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT NOT NULL)",
            "params": [],
        },
    ).raise_for_status()
    r = api_client.post(
        "/v1/batch",
        json={
            "ops": [
                {
                    "type": "execute",
                    "sql": "INSERT INTO t (v) VALUES (?)",
                    "params": ["ok"],
                },
                {
                    "type": "execute",
                    "sql": "INSERT INTO missing (v) VALUES (?)",
                    "params": ["x"],
                },
            ]
        },
    )
    assert r.status_code == 400
    assert "error" in r.json()
    count = api_client.post(
        "/v1/query",
        json={"sql": "SELECT COUNT(*) AS n FROM t", "params": []},
    ).json()
    assert count["rows"] == [{"n": 0}]


def test_sql_error_is_400(api_client: TestClient) -> None:
    r = api_client.post(
        "/v1/query",
        json={"sql": "SELECT * FROM nonexistent", "params": []},
    )
    assert r.status_code == 400
    assert "no such table" in r.json()["error"].lower()


def test_internal_error_is_500_without_leak(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(sql: str, params: object = ()) -> object:
        raise RuntimeError("secret internals")

    monkeypatch.setattr(api_client.app.state.db, "execute", boom)
    r = api_client.post(
        "/v1/execute",
        json={"sql": "SELECT 1", "params": []},
    )
    assert r.status_code == 500
    assert r.json() == {"error": "internal error"}


def test_body_too_large(api_client: TestClient) -> None:
    r = api_client.post(
        "/v1/execute",
        content=b"{}",
        headers={
            "content-type": "application/json",
            "content-length": str(api_mod.SqlApi.MAX_BODY_BYTES + 1),
        },
    )
    assert r.status_code == 413
    assert r.json()["error"] == "request body too large"


def test_batch_invalid_type_is_400(api_client: TestClient) -> None:
    r = api_client.post(
        "/v1/batch",
        json={
            "ops": [
                {
                    "type": "drop",
                    "sql": "SELECT 1",
                    "params": [],
                }
            ]
        },
    )
    assert r.status_code == 422  # Pydantic rejects unknown Literal


def test_body_too_large_without_content_length(api_client: TestClient) -> None:
    huge = b"x" * (api_mod.SqlApi.MAX_BODY_BYTES + 1)
    r = api_client.post(
        "/v1/execute",
        content=huge,
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 413
    assert r.json()["error"] == "request body too large"


def test_flush(api_client: TestClient, volume: modal.Volume) -> None:
    r = api_client.post("/v1/flush", json={})
    assert r.status_code == 200
    cast(MagicMock, volume.commit).assert_called()


def test_lifespan_commit_on_shutdown(
    temp_db_path: Path,
    volume: modal.Volume,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SQLITE_MODAL_NAME", "test-db")

    def fake_from_name(name: str) -> modal.Volume:
        return volume

    monkeypatch.setattr(api_mod.modal.Volume, "from_name", fake_from_name)
    monkeypatch.setattr(api_mod.Database, "DEFAULT_PATH", temp_db_path)

    with TestClient(api_mod.app) as client:
        client.post(
            "/v1/execute",
            json={
                "sql": "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)",
                "params": [],
            },
        ).raise_for_status()
    cast(MagicMock, volume.commit).assert_called()
