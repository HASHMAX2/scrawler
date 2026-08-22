"""Tracks which source files have already been imported (by content hash) so
`refresh_data.py` can skip unchanged files and only reprocess what's new or
modified.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import duckdb

DDL = """
CREATE TABLE IF NOT EXISTS file_registry (
    file_path VARCHAR PRIMARY KEY,
    file_hash VARCHAR NOT NULL,
    size_bytes BIGINT NOT NULL,
    modified_at TIMESTAMP NOT NULL,
    imported_at TIMESTAMP NOT NULL,
    dataset_type VARCHAR NOT NULL,
    row_count BIGINT NOT NULL,
    status VARCHAR NOT NULL
);
"""


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def file_hash(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def needs_import(con: duckdb.DuckDBPyConnection, path: Path) -> bool:
    """A file needs (re)import if it's new or its content hash changed since
    the last successful import. Renames/moves without content changes still
    count as new (file_path is the key) — acceptable for this use case since
    files are dropped into a fixed data directory, not moved around.
    """
    h = file_hash(path)
    row = con.execute(
        "SELECT file_hash, status FROM file_registry WHERE file_path = ?",
        [str(path)],
    ).fetchone()
    if row is None:
        return True
    existing_hash, status = row
    return existing_hash != h or status != "success"


def record_import(
    con: duckdb.DuckDBPyConnection,
    path: Path,
    dataset_type: str,
    row_count: int,
    status: str = "success",
) -> None:
    con.execute(
        """
        INSERT INTO file_registry (file_path, file_hash, size_bytes, modified_at, imported_at, dataset_type, row_count, status)
        VALUES (?, ?, ?, ?, now(), ?, ?, ?)
        ON CONFLICT (file_path) DO UPDATE SET
            file_hash = excluded.file_hash,
            size_bytes = excluded.size_bytes,
            modified_at = excluded.modified_at,
            imported_at = excluded.imported_at,
            dataset_type = excluded.dataset_type,
            row_count = excluded.row_count,
            status = excluded.status
        """,
        [
            str(path),
            file_hash(path),
            path.stat().st_size,
            datetime.fromtimestamp(path.stat().st_mtime),
            dataset_type,
            row_count,
            status,
        ],
    )
