"""Public client — from_name, attach, HTTP SQL."""

from __future__ import annotations

import os
import re
import time
import weakref
from collections.abc import Mapping, Sequence
from typing import Any, Self, cast

import httpx
import modal

from sqlite_modal.database import BatchOp, Database, ExecuteResult, Row, SqlParams
from sqlite_modal.exceptions import (
    AlreadyAttachedError,
    AuthError,
    ConfigError,
    InvalidNameError,
    NotAttachedError,
    ServiceError,
    SqlError,
)
from sqlite_modal.server import Server

# Names attached per App (many Sqlites allowed; duplicate names are not).
_attached_names: weakref.WeakKeyDictionary[modal.App, set[str]] = (
    weakref.WeakKeyDictionary()
)


class Sqlite:
    """Named SQLite on Modal.

    Lifecycle: ``from_name`` → ``attach`` → ``query`` / ``execute`` / ``batch``.

    Many Sqlites per App (one Modal Server + Volume each). Exclusivity comes from
    a Server singleton (``target_concurrency`` unset); ``min_containers`` only
    controls warmth.
    """

    _NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")

    def __init__(
        self,
        name: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 40,
    ) -> None:
        if not self._NAME_RE.fullmatch(name):
            raise InvalidNameError(f"invalid Sqlite name {name!r}")
        if timeout <= 0:
            raise ConfigError("timeout must be > 0")
        if max_retries < 1:
            raise ConfigError("max_retries must be >= 1")
        self.name = name
        self._timeout = timeout
        self._max_retries = max_retries
        self._attached_app: modal.App | None = None
        self._server: modal.Server | None = None
        self._http: httpx.Client | None = None
        self._proxy_headers_cache: dict[str, str] | None = None

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        timeout: float = 60.0,
        max_retries: int = 40,
    ) -> Self:
        return cls(name, timeout=timeout, max_retries=max_retries)

    def __repr__(self) -> str:
        return (
            f"Sqlite(name={self.name!r}, attached={self._attached_app is not None})"
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None
        self._proxy_headers_cache = None

    @staticmethod
    def default_image() -> modal.Image:
        return (
            modal.Image.debian_slim(python_version="3.12")
            .pip_install(*Server.PIP_PACKAGES)
            .add_local_python_source("sqlite_modal")
        )

    def attach(
        self,
        app: modal.App,
        *,
        image: modal.Image | None = None,
        region: str,
        cloud: str,
        min_containers: int = 0,
        scaledown_window: int = 5 * 60,
        startup_timeout: int = 120,
        exit_grace_period: int = 15,
    ) -> Self:
        """Register this DB’s Server + Volume on ``app``."""
        if min_containers not in (0, 1):
            raise ConfigError("min_containers must be 0 or 1 (warmth only)")

        if self._attached_app is not None:
            if self._attached_app == app:
                raise AlreadyAttachedError(
                    f"Sqlite {self.name!r} is already attached to app {app.name!r}"
                )
            raise AlreadyAttachedError(
                f"already attached to app {self._attached_app.name!r}; "
                f"cannot attach to {app.name!r}"
            )

        names = _attached_names.get(app)
        if names is not None and self.name in names:
            raise AlreadyAttachedError(
                f"app {app.name!r} already has Sqlite {self.name!r} attached"
            )

        volume = modal.Volume.from_name(f"{self.name}-data", create_if_missing=True)
        self._server = app.server(
            image=image if image is not None else self.default_image(),
            volumes={str(Database.VOLUME_MOUNT): volume},
            env={"SQLITE_MODAL_NAME": self.name},
            serialized=True,
            min_containers=min_containers,
            scaledown_window=scaledown_window,
            startup_timeout=startup_timeout,
            exit_grace_period=exit_grace_period,
            port=Server.HTTP_PORT,
            unauthenticated=False,
            routing_region=region,
            compute_region=region,
            cloud=cloud,
        )(Server.for_name(self.name))
        self._attached_app = app
        if names is None:
            names = set()
            _attached_names[app] = names
        names.add(self.name)
        return self

    @property
    def url(self) -> str:
        if self._server is None:
            raise NotAttachedError(
                f"Sqlite {self.name!r} is not attached; call attach(app, ...) first"
            )
        url = self._server.get_url()
        if not url:
            raise ServiceError(
                "Server has no URL yet — run `modal serve` or `modal deploy` first"
            )
        return url

    def _proxy_headers(self) -> dict[str, str]:
        if self._proxy_headers_cache is not None:
            return self._proxy_headers_cache
        token_id = os.environ.get("MODAL_PROXY_TOKEN_ID")
        token_secret = os.environ.get("MODAL_PROXY_TOKEN_SECRET")
        if not token_id or not token_secret:
            raise AuthError(
                "Sqlite Server auth requires proxy tokens. "
                "Set MODAL_PROXY_TOKEN_ID / MODAL_PROXY_TOKEN_SECRET "
                "(wk-… / ws-…), e.g. `modal workspace proxy-tokens create` "
                "then `modal workspace proxy-tokens allow <id> main`"
            )
        self._proxy_headers_cache = {
            "Modal-Key": token_id,
            "Modal-Secret": token_secret,
        }
        return self._proxy_headers_cache

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(
                timeout=self._timeout,
                limits=httpx.Limits(
                    max_connections=32, max_keepalive_connections=16
                ),
            )
        return self._http

    def _post(
        self,
        path: str,
        body: Mapping[str, Any],
        *,
        idempotent: bool,
    ) -> httpx.Response:
        headers = {**self._proxy_headers(), "content-type": "application/json"}
        url = f"{self.url}{path}"
        client = self._http_client()
        delay = 0.05
        last: httpx.Response | None = None
        last_exc: BaseException | None = None
        attempts = 0
        for attempt in range(1, self._max_retries + 1):
            attempts = attempt
            try:
                last = client.post(url, json=body, headers=headers)
                last_exc = None
            except httpx.ConnectError as exc:
                last_exc = exc
                last = None
                time.sleep(delay)
                delay = min(delay * 1.5, 1.0)
                continue
            except httpx.TransportError as exc:
                if not idempotent:
                    raise ServiceError(
                        f"POST {path}: transport error after send "
                        f"(attempt {attempt})"
                    ) from exc
                last_exc = exc
                last = None
                time.sleep(delay)
                delay = min(delay * 1.5, 1.0)
                continue
            if last.status_code != 503:
                break
            time.sleep(delay)
            delay = min(delay * 1.5, 1.0)
        else:
            if last_exc is not None:
                raise ServiceError(
                    f"POST {path}: no response after {attempts} attempts"
                ) from last_exc
            raise ServiceError(
                f"POST {path}: no response after {attempts} attempts"
            )
        if last is None:
            raise ServiceError(f"POST {path}: no response after {attempts} attempts")
        if not last.is_success:
            try:
                payload = last.json()
                msg = (
                    payload.get("error")
                    if isinstance(payload, dict)
                    else None
                ) or last.text
            except Exception:
                msg = last.text
            if last.status_code == 401:
                raise AuthError(msg)
            if last.status_code == 413:
                raise ServiceError(f"Sqlite HTTP 413: {msg}")
            if 400 <= last.status_code < 500:
                raise SqlError(msg, status_code=last.status_code)
            raise ServiceError(f"Sqlite HTTP {last.status_code}: {msg}")
        return last

    def query(self, statement: str, params: SqlParams = ()) -> list[Row]:
        response = self._post(
            "/v1/query",
            {"sql": statement, "params": list(params)},
            idempotent=True,
        )
        try:
            return cast(list[Row], response.json()["rows"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("POST /v1/query: invalid response body") from exc

    def execute(self, statement: str, params: SqlParams = ()) -> ExecuteResult:
        response = self._post(
            "/v1/execute",
            {"sql": statement, "params": list(params)},
            idempotent=False,
        )
        try:
            body = response.json()
            return cast(
                ExecuteResult,
                {"rowcount": body["rowcount"], "lastrowid": body["lastrowid"]},
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("POST /v1/execute: invalid response body") from exc

    def executemany(
        self, statement: str, params_seq: Sequence[SqlParams]
    ) -> ExecuteResult:
        """One statement, many param rows, one HTTP round-trip.

        Empty ``params_seq`` skips the HTTP round-trip.
        """
        if not params_seq:
            return {"rowcount": 0, "lastrowid": 0}
        results = self.batch(
            [
                {
                    "type": "execute",
                    "sql": statement,
                    "params_seq": [list(row) for row in params_seq],
                }
            ]
        )
        return cast(ExecuteResult, results[0])

    def batch(
        self, ops: Sequence[BatchOp]
    ) -> list[ExecuteResult | dict[str, list[Row]]]:
        response = self._post(
            "/v1/batch", {"ops": list(ops)}, idempotent=False
        )
        try:
            return cast(
                list[ExecuteResult | dict[str, list[Row]]],
                response.json()["results"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError("POST /v1/batch: invalid response body") from exc

    def flush(self) -> None:
        self._post("/v1/flush", {}, idempotent=False)
