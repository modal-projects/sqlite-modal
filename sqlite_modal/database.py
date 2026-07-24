"""Named Sqlite handle — Modal naming + Turso ``connect``."""

from __future__ import annotations

import re
from pathlib import Path

import modal
from modal.exception import NotFoundError
from turso.sync import ConnectionSync, connect

from sqlite_modal.exceptions import InvalidNameError, MissingError
from sqlite_modal.remote import CreateOptions, RemoteApp
from sqlite_modal.turso import APP_PREFIX, REMOTE_NAME, VOLUME_NAME

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")


class Sqlite:
    """Modal-named Turso Sync database.

    Each name is its own Modal App (``sqlite-modal-{name}``) running one
    ``tursodb`` sync Server::

        db = Sqlite.from_name("orders", create_if_missing=True, create_options={...})
    """

    def __init__(
        self,
        name: str,
        *,
        environment_name: str | None = None,
        client: modal.Client | None = None,
    ) -> None:
        if not NAME_RE.fullmatch(name):
            raise InvalidNameError(
                f"invalid Sqlite name {name!r}; "
                "expected ^[A-Za-z][A-Za-z0-9_]{0,127}$"
            )
        self.name = name
        self.environment_name = environment_name
        self.client = client
        self.server: modal.Server | None = None
        self.url: str | None = None

    def __repr__(self) -> str:
        return f"Sqlite(name={self.name!r})"

    @property
    def app_name(self) -> str:
        return f"{APP_PREFIX}-{self.name}"

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        environment_name: str | None = None,
        create_if_missing: bool = False,
        create_options: CreateOptions | None = None,
        client: modal.Client | None = None,
    ) -> Sqlite:
        if create_options is not None and not create_if_missing:
            raise ValueError("create_options requires create_if_missing=True")

        db = cls(name, environment_name=environment_name, client=client)
        if create_if_missing:
            modal.Volume.from_name(
                VOLUME_NAME,
                create_if_missing=True,
                environment_name=environment_name,
                client=client,
            )
            RemoteApp.deploy(
                name,
                create_options=create_options,
                environment_name=environment_name,
                client=client,
            )
            return db

        if not db.exists():
            raise MissingError(
                f"Sqlite {name!r} does not exist; "
                "pass create_if_missing=True to create it"
            )
        return db

    @property
    def remote_url(self) -> str:
        """Bare sync URL for ``turso.sync.connect(..., remote_url=...)``."""
        if self.url is not None:
            return self.url
        try:
            base = self.resolve_server().get_url()
        except NotFoundError as exc:
            raise RuntimeError(
                f"sync URL unavailable for {self.name!r}; "
                f"create with Sqlite.from_name({self.name!r}, "
                f"create_if_missing=True)"
            ) from exc
        if not base:
            raise RuntimeError(
                f"sync URL unavailable for {self.name!r}; "
                f"create with Sqlite.from_name({self.name!r}, "
                f"create_if_missing=True)"
            )
        self.url = base.rstrip("/")
        return self.url

    def connect(self, path: str | Path) -> ConnectionSync:
        """``turso.sync.connect(path, remote_url=self.remote_url)``."""
        path_str = str(path)
        if not path_str:
            raise ValueError("connect() requires a non-empty local path")
        return connect(path_str, remote_url=self.remote_url)

    def resolve_server(self) -> modal.Server:
        if self.server is None:
            self.server = modal.Server.from_name(
                self.app_name,
                REMOTE_NAME,
                environment_name=self.environment_name,
                client=self.client,
            )
        return self.server

    def exists(self) -> bool:
        try:
            return bool(self.resolve_server().get_url())
        except NotFoundError:
            return False
