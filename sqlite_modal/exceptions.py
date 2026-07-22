"""Public exception types for sqlite_modal."""

from __future__ import annotations


class SqliteError(Exception):
    """Base error for sqlite_modal."""


class InvalidNameError(SqliteError):
    """Invalid Sqlite name (identifier regex)."""


class ConfigError(SqliteError):
    """Invalid client or attach configuration."""


class NotAttachedError(SqliteError):
    """Operation requires ``attach`` first."""


class AlreadyAttachedError(SqliteError):
    """Sqlite already attached to an App, or name already taken on that App."""


class AuthError(SqliteError):
    """Missing or invalid Modal proxy token credentials."""


class SqlError(SqliteError):
    """SQL / client fault from the Server (HTTP 4xx)."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ServiceError(SqliteError):
    """Transport failure, HTTP 5xx, or retries exhausted."""
