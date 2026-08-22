"""Raw CSV -> DuckDB staging tables, one row per source row, all columns kept
as VARCHAR plus lineage columns. Uses pandas (not DuckDB's parallel CSV
reader) specifically so row order — and therefore `row_num` — is deterministic
across re-runs; DuckDB's CSV reader can parallelize large files, which would
make a `ROW_NUMBER() OVER ()` window unstable and break the row_uid identity
that fact-table idempotency depends on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from ingestion.file_registry import file_hash
from ingestion.schema_registry import DatasetSpec


def load_csv_to_staging(con: duckdb.DuckDBPyConnection, path: Path, spec: DatasetSpec) -> int:
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, low_memory=False, keep_default_na=False, na_values=[""])
    df.insert(0, "row_num", range(len(df)))
    df.insert(1, "source_file", str(path))
    df.insert(2, "file_hash", file_hash(path))
    df.insert(3, "imported_at", datetime.now(timezone.utc))

    con.register("_stg_incoming", df)
    columns_sql = ", ".join(f'"{c}"' for c in df.columns)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS {spec.staging_table} AS
        SELECT {columns_sql} FROM _stg_incoming WHERE 1=0
    """)
    con.execute(f"DELETE FROM {spec.staging_table} WHERE source_file = ?", [str(path)])
    con.execute(f"INSERT INTO {spec.staging_table} SELECT {columns_sql} FROM _stg_incoming")
    con.unregister("_stg_incoming")
    return len(df)
