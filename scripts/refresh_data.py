#!/usr/bin/env python
"""Scan configured data directories for known dataset files, stage any that
are new or changed (by content hash), and rebuild the DuckDB warehouse
(dim_area, dim_project, fact_sales, fact_rentals) from current staging
contents + the attached scraper SQLite database.

Usage:
    python scripts/refresh_data.py [--data-dir "DATA FILES DLD"] [--db data/warehouse.duckdb]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from ingestion import file_registry, sources, staging, warehouse  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(ROOT / "DATA FILES DLD"), help="Directory to scan for DLD CSV exports")
    ap.add_argument("--db", default=str(ROOT / "data" / "warehouse.duckdb"))
    ap.add_argument("--scraped-db", default=str(ROOT / "data" / "propsearch.db"))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    con = duckdb.connect(args.db)
    file_registry.ensure_schema(con)
    warehouse.ensure_schema(con)

    found = sources.scan_directory(data_dir)
    skipped = sources.unrecognized_files(data_dir)
    if skipped:
        print(f"Skipping {len(skipped)} unrecognized file(s) in {data_dir}:")
        for p in skipped:
            print(f"  - {p.name}")

    if not found:
        print(f"No recognized dataset files found in {data_dir}")
    changed = 0
    for path, spec in found:
        if not file_registry.needs_import(con, path):
            print(f"  [skip, unchanged] {path.name} ({spec.dataset_type})")
            continue
        t0 = time.time()
        n = staging.load_csv_to_staging(con, path, spec)
        file_registry.record_import(con, path, spec.dataset_type, n)
        changed += 1
        print(f"  [staged] {path.name} ({spec.dataset_type}): {n:,} rows in {time.time()-t0:.1f}s")

    print("Rebuilding warehouse (dims + facts)...")
    t0 = time.time()
    counts = warehouse.build_warehouse(con, Path(args.scraped_db))
    print(f"  done in {time.time()-t0:.1f}s: {counts}")
    con.close()


if __name__ == "__main__":
    main()
