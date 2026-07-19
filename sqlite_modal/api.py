"""HTTP API — FastAPI app served by uvicorn in the Server container."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Literal, TypeVar

import modal
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sqlite_modal.database import BatchOp, Database, SqlParam

logger = logging.getLogger("sqlite_modal.api")

T = TypeVar("T")


class SqlBody(BaseModel):
    sql: str
    params: list[SqlParam] = Field(default_factory=list)


class BatchOpBody(BaseModel):
    type: Literal["query", "execute"]
    sql: str
    params: list[SqlParam] = Field(default_factory=list)
    params_seq: list[list[SqlParam]] | None = None

    @field_validator("params_seq")
    @classmethod
    def _cap_params_seq(
        cls, value: list[list[SqlParam]] | None
    ) -> list[list[SqlParam]] | None:
        if value is not None and len(value) > Database.MAX_PARAMS_SEQ:
            raise ValueError(f"params_seq exceeds {Database.MAX_PARAMS_SEQ} rows")
        return value


class BatchBody(BaseModel):
    ops: list[BatchOpBody]

    @field_validator("ops")
    @classmethod
    def _cap_ops(cls, value: list[BatchOpBody]) -> list[BatchOpBody]:
        if len(value) > Database.MAX_BATCH_OPS:
            raise ValueError(f"batch exceeds {Database.MAX_BATCH_OPS} ops")
        return value

    def as_batch_ops(self) -> list[BatchOp]:
        out: list[BatchOp] = []
        for op in self.ops:
            item: BatchOp = {"type": op.type, "sql": op.sql}
            if op.params_seq is not None:
                item["params_seq"] = op.params_seq
            else:
                item["params"] = op.params
            out.append(item)
        return out


class BodySizeLimit:
    """Reject request bodies larger than ``max_bytes``."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                await JSONResponse(
                    {"error": "invalid content-length"}, status_code=400
                )(scope, receive, send)
                return
            if length > self.max_bytes:
                await JSONResponse(
                    {"error": "request body too large"}, status_code=413
                )(scope, receive, send)
                return

        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            if chunk:
                body.extend(chunk)
            if len(body) > self.max_bytes:
                await JSONResponse(
                    {"error": "request body too large"}, status_code=413
                )(scope, receive, send)
                return
            more_body = bool(message.get("more_body", False))

        payload = bytes(body)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": payload, "more_body": False}

        await self.app(scope, replay, send)


class SqlApi:
    """HTTP SQL surface over a ``Database`` held on the FastAPI app state."""

    MAX_BODY_BYTES = 16 * 1024 * 1024

    def __init__(self) -> None:
        self.app = FastAPI(title="sqlite-modal", lifespan=self.lifespan)
        self.app.add_middleware(BodySizeLimit, max_bytes=self.MAX_BODY_BYTES)
        self.app.add_api_route("/health", self.health, methods=["GET"])
        self.app.add_api_route("/v1/execute", self.execute, methods=["POST"])
        self.app.add_api_route("/v1/query", self.query, methods=["POST"])
        self.app.add_api_route("/v1/batch", self.batch, methods=["POST"])
        self.app.add_api_route("/v1/flush", self.flush, methods=["POST"])

    @asynccontextmanager
    async def lifespan(self, api: FastAPI) -> AsyncIterator[None]:
        name = os.environ["SQLITE_MODAL_NAME"]
        volume = modal.Volume.from_name(f"{name}-data")
        api.state.db = Database.from_path(Database.DEFAULT_PATH, volume)
        try:
            yield
        finally:
            db: Database = api.state.db
            await asyncio.to_thread(db.close, commit=True)

    def _run(self, fn: Callable[[], T]) -> JSONResponse | T:
        try:
            return fn()
        except (sqlite3.Error, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sqlite_modal api internal error: %s", exc)
            return JSONResponse({"error": "internal error"}, status_code=500)

    def health(self) -> JSONResponse:
        db: Database = self.app.state.db
        try:
            db.query("SELECT 1")
            return JSONResponse({"ok": True})
        except Exception as exc:  # noqa: BLE001
            logger.exception("health check failed: %s", exc)
            return JSONResponse(
                {"ok": False, "error": "internal error"}, status_code=503
            )

    def execute(self, body: SqlBody) -> JSONResponse:
        db: Database = self.app.state.db
        result = self._run(lambda: db.execute(body.sql, body.params))
        return result if isinstance(result, JSONResponse) else JSONResponse(result)

    def query(self, body: SqlBody) -> JSONResponse:
        db: Database = self.app.state.db
        result = self._run(lambda: db.query(body.sql, body.params))
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse({"rows": result})

    def batch(self, body: BatchBody) -> JSONResponse:
        db: Database = self.app.state.db
        result = self._run(lambda: db.batch(body.as_batch_ops()))
        if isinstance(result, JSONResponse):
            return result
        return JSONResponse({"results": result})

    def flush(self) -> JSONResponse:
        db: Database = self.app.state.db
        result = self._run(db.flush)
        return result if isinstance(result, JSONResponse) else JSONResponse({})


api = SqlApi()
app = api.app
