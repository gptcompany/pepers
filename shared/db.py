"""SQLite database layer for the research pipeline.

Provides connection management with WAL mode and foreign keys enabled.
All services share the same database file via this module.

Usage:
    from shared.db import get_connection, init_db

    # Initialize database (creates tables if needed)
    init_db("/path/to/research.db")

    # Get a connection (context manager for auto-commit/rollback)
    with get_connection("/path/to/research.db") as conn:
        cursor = conn.execute("SELECT * FROM papers")
        rows = cursor.fetchall()

Design decisions:
- WAL mode for concurrent read access (orchestrator reads while service writes)
- Foreign keys enforced at connection level
- Row factory returns sqlite3.Row for dict-like access
- Single connection per request (no pool needed for ~10 papers/day batch)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode and foreign keys.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Configured sqlite3.Connection with WAL mode and foreign keys enabled.
    """
    ...


@contextmanager
def transaction(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    """Context manager that provides a connection with auto-commit/rollback.

    Commits on success, rolls back on exception.

    Args:
        db_path: Path to the SQLite database file.

    Yields:
        sqlite3.Connection within a transaction.
    """
    ...


def init_db(db_path: str | Path) -> None:
    """Initialize the database schema.

    Creates all tables if they don't exist. Idempotent.

    Args:
        db_path: Path to the SQLite database file.
    """
    ...
