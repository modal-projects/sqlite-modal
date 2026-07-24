"""Public exception types for sqlite_modal."""

from __future__ import annotations


class SqliteError(Exception):
    """Base error for sqlite_modal."""


class InvalidNameError(SqliteError):
    """Invalid database name."""


class MissingError(SqliteError):
    """Named database does not exist and create_if_missing is False."""
