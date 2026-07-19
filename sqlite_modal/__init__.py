"""Named SQLite on Modal Servers.

Public API: ``Sqlite`` (from_name / attach / query / execute / executemany /
batch / flush / close), ``BatchOp``, ``ExecuteResult``, ``Row``, and exception
types. Many Sqlites per App (one Server each).
"""

from sqlite_modal.client import Sqlite
from sqlite_modal.database import BatchOp, ExecuteResult, Row
from sqlite_modal.exceptions import (
    AlreadyAttachedError,
    AuthError,
    ConfigError,
    InvalidNameError,
    NotAttachedError,
    ServiceError,
    SqlError,
    SqliteError,
)

__all__ = [
    "AlreadyAttachedError",
    "AuthError",
    "BatchOp",
    "ConfigError",
    "ExecuteResult",
    "InvalidNameError",
    "NotAttachedError",
    "Row",
    "ServiceError",
    "SqlError",
    "Sqlite",
    "SqliteError",
]
