"""SQL HTTP API — FastAPI app served by uvicorn in the Server container."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import modal
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from sqlite_modal.db import (
    DEFAULT_DB_PATH,
    BatchRequest,
    Database,
    SqlRequest,
)

logger = logging.getLogger("sqlite_modal.api")

MAX_BODY_BYTES = 16 * 1024 * 1024


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self, app: ASGIApp, max_body_bytes: int = MAX_BODY_BYTES
    ) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    {"error": "invalid content-length"}, status_code=400
                )
            if length > self._max_body_bytes:
                return JSONResponse(
                    {"error": "request body too large"}, status_code=413
                )
        return await call_next(request)


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncIterator[None]:
    name = os.environ["SQLITE_MODAL_NAME"]
    volume = modal.Volume.from_name(f"{name}-data")
    api.state.db = Database.from_path(DEFAULT_DB_PATH, volume)
    try:
        yield
    finally:
        db: Database = api.state.db
        db.close()


app = FastAPI(title="sqlite-modal", lifespan=lifespan)
app.add_middleware(_BodySizeLimitMiddleware)


def _sql_error_response(exc: sqlite3.Error) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=400)


def _internal_error_response(exc: BaseException) -> JSONResponse:
    logger.exception("sqlite_modal api internal error: %s", exc)
    return JSONResponse({"error": "internal error"}, status_code=500)


@app.get("/health")
def health() -> JSONResponse:
    db: Database = app.state.db
    try:
        db.query("SELECT 1")
        return JSONResponse({"ok": True})
    except sqlite3.Error as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=503)
    except Exception as exc:  # noqa: BLE001
        logger.exception("health check internal error: %s", exc)
        return JSONResponse(
            {"ok": False, "error": "internal error"}, status_code=503
        )


@app.post("/v1/execute")
def http_execute(body: SqlRequest) -> JSONResponse:
    db: Database = app.state.db
    try:
        return JSONResponse(db.execute(body["sql"], body["params"]))
    except sqlite3.Error as exc:
        return _sql_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response(exc)


@app.post("/v1/query")
def http_query(body: SqlRequest) -> JSONResponse:
    db: Database = app.state.db
    try:
        rows = db.query(body["sql"], body["params"])
        return JSONResponse({"rows": rows})
    except sqlite3.Error as exc:
        return _sql_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response(exc)


@app.post("/v1/batch")
def http_batch(body: BatchRequest) -> JSONResponse:
    db: Database = app.state.db
    try:
        results = db.batch(body["ops"])
        return JSONResponse({"results": results})
    except sqlite3.Error as exc:
        return _sql_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response(exc)


@app.post("/v1/flush")
def http_flush() -> JSONResponse:
    db: Database = app.state.db
    try:
        db.flush()
        return JSONResponse({})
    except sqlite3.Error as exc:
        return _sql_error_response(exc)
    except Exception as exc:  # noqa: BLE001
        return _internal_error_response(exc)
