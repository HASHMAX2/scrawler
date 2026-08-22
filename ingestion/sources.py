"""Scans configured data directories, fingerprints CSV files by header, and
returns the (path, DatasetSpec) pairs ready for staging.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ingestion.schema_registry import DatasetSpec, detect


def read_header(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        return next(reader)


def scan_directory(directory: Path) -> list[tuple[Path, DatasetSpec]]:
    """Return every CSV under `directory` whose header matches a known
    DatasetSpec. Files with an unrecognized header are skipped (not raised)
    so an unrelated CSV dropped in the same folder doesn't break a refresh —
    callers should log the skip so it isn't silently invisible.
    """
    found: list[tuple[Path, DatasetSpec]] = []
    if not directory.exists():
        return found
    for path in sorted(directory.glob("*.csv")):
        try:
            header = read_header(path)
        except (StopIteration, OSError):
            continue
        spec = detect(header)
        if spec is not None:
            found.append((path, spec))
    return found


def unrecognized_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    matched = {p for p, _ in scan_directory(directory)}
    return [p for p in sorted(directory.glob("*.csv")) if p not in matched]
