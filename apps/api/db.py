"""DuckDB connection management.

FastAPI runs sync `def` route handlers in a thread pool, so multiple
requests can be in flight concurrently on different threads. A single
`duckdb.DuckDBPyConnection` is NOT safe to call `.execute()`/`.fetchall()`
on from multiple threads at once — interleaved calls corrupt each other's
result state (observed directly: a `date_trunc` query intermittently
returned VARCHAR rows instead of the expected DATE column under concurrent
load). The base connection is opened once at startup (so ATTACH/catalog
load only happens once); every request gets its own `.cursor()` — a cheap,
independent handle onto the same open database, safe for concurrent use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import duckdb

ROOT = Path(__file__).resolve().parent.parent.parent
WAREHOUSE_PATH = ROOT / "data" / "warehouse.duckdb"

_connection: duckdb.DuckDBPyConnection | None = None


def get_shared_connection() -> duckdb.DuckDBPyConnection:
    global _connection
    if _connection is None:
        _connection = duckdb.connect(str(WAREHOUSE_PATH), read_only=False)
    return _connection


def db() -> Iterator[duckdb.DuckDBPyConnection]:
    """FastAPI dependency: a fresh cursor per request."""
    cursor = get_shared_connection().cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def close_shared_connection() -> None:
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
