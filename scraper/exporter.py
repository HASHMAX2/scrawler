"""CSV/JSON export of the SQLite database (brief §22).

Every export is computed directly from the current database state — nothing here
hardcodes a number or a row; it's a straight `SELECT *` per table dumped to file.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

TABLES = [
    "areas", "developments", "buildings", "unit_supply", "transactions",
    "amenities", "schools", "developers", "construction_history",
    "construction_milestones", "sub_communities", "documents",
]


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(f"SELECT * FROM {table}")
    return [dict(r) for r in cur.fetchall()]


def export_csv(db_path: str | Path, out_dir: str | Path, tables: list[str] | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    written = []
    try:
        for table in tables or TABLES:
            rows = _rows(conn, table)
            path = out_dir / f"{table}.csv"
            if not rows:
                path.write_text("", encoding="utf-8")
                written.append(path)
                continue
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            written.append(path)
    finally:
        conn.close()
    return written


def export_json(db_path: str | Path, out_dir: str | Path, tables: list[str] | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    written = []
    try:
        for table in tables or TABLES:
            rows = _rows(conn, table)
            path = out_dir / f"{table}.json"
            path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
            written.append(path)
    finally:
        conn.close()
    return written


def export_combined_json(db_path: str | Path, out_path: str | Path) -> Path:
    """One nested JSON file: developments (with their buildings + unit supply +
    transactions inlined), grouped under their area. Practical for a quick full-data
    handoff without joining CSVs by hand.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        areas = _rows(conn, "areas")
        for area in areas:
            devs = [dict(r) for r in conn.execute(
                "SELECT * FROM developments WHERE area_id=?", (area["id"],)
            ).fetchall()]
            for dev in devs:
                dev["buildings"] = [dict(r) for r in conn.execute(
                    "SELECT * FROM buildings WHERE development_id=?", (dev["id"],)
                ).fetchall()]
                unit_row = conn.execute(
                    "SELECT * FROM unit_supply WHERE development_id=?", (dev["id"],)
                ).fetchone()
                dev["unit_supply"] = dict(unit_row) if unit_row else None
                dev["transactions"] = [dict(r) for r in conn.execute(
                    "SELECT * FROM transactions WHERE development_id=?", (dev["id"],)
                ).fetchall()]
                dev["construction_history"] = [dict(r) for r in conn.execute(
                    "SELECT * FROM construction_history WHERE development_id=?", (dev["id"],)
                ).fetchall()]
                dev["milestones"] = [dict(r) for r in conn.execute(
                    "SELECT * FROM construction_milestones WHERE development_id=?", (dev["id"],)
                ).fetchall()]
            area["developments"] = devs
            area["sub_communities"] = [dict(r) for r in conn.execute(
                "SELECT * FROM sub_communities WHERE parent_area_id=?", (area["id"],)
            ).fetchall()]
            area["amenities"] = [dict(r) for r in conn.execute(
                "SELECT * FROM amenities WHERE area_id=?", (area["id"],)
            ).fetchall()]
            area["schools"] = [dict(r) for r in conn.execute(
                "SELECT * FROM schools WHERE area_id=?", (area["id"],)
            ).fetchall()]
        out_path.write_text(json.dumps(areas, indent=2, default=str), encoding="utf-8")
    finally:
        conn.close()
    return out_path


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Export the Propsearch SQLite database to CSV/JSON")
    ap.add_argument("--db", default="data/propsearch.db")
    ap.add_argument("--out", default="exports")
    ap.add_argument("--format", choices=["csv", "json", "both"], default="both")
    ap.add_argument("--combined", action="store_true", help="Also write a nested combined JSON file")
    args = ap.parse_args()

    if args.format in ("csv", "both"):
        paths = export_csv(args.db, args.out)
        print(f"Wrote {len(paths)} CSV files to {args.out}/")
    if args.format in ("json", "both"):
        paths = export_json(args.db, args.out)
        print(f"Wrote {len(paths)} JSON files to {args.out}/")
    if args.combined:
        path = export_combined_json(args.db, Path(args.out) / "combined.json")
        print(f"Wrote combined export to {path}")
