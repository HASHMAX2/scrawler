from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from apps.api.db import ROOT, db
from ingestion import file_registry, sources, staging, warehouse
from ingestion.schema_registry import detect

router = APIRouter()

IMPORT_DIR = ROOT / "DATA FILES DLD"
SCRAPED_DB = ROOT / "data" / "propsearch.db"


@router.post("/upload")
async def upload_file(file: UploadFile, con=Depends(db)):
    """Accepts a CSV, detects its dataset type by header, stages it, and
    rebuilds the warehouse. This is synchronous and can take ~1-3 minutes on
    the full historical dataset size — a known limitation (the current
    ingestion design always fully rebuilds dim/fact tables on refresh; see
    docs/DATA_MODEL.md). The UI should show a spinner, not a fixed timeout.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Only .csv files are supported")

    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    dest = IMPORT_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)

    header = sources.read_header(dest)
    spec = detect(header)
    if spec is None:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Unrecognized CSV shape for {file.filename} — header doesn't match any known dataset (dld_sales/dld_rentals). Columns must match exactly.")

    warehouse.ensure_schema(con)
    file_registry.ensure_schema(con)
    n = staging.load_csv_to_staging(con, dest, spec)
    file_registry.record_import(con, dest, spec.dataset_type, n)
    counts = warehouse.build_warehouse(con, SCRAPED_DB)

    return {"status": "imported", "file": file.filename, "dataset_type": spec.dataset_type, "rows_staged": n, "warehouse": counts}


@router.post("/refresh")
def refresh_from_directory(con=Depends(db)):
    """Re-scan DATA FILES DLD for new/changed files and rebuild — same
    operation as scripts/refresh_data.py, exposed for the Import Data screen's
    "Refresh Data" button.
    """
    warehouse.ensure_schema(con)
    file_registry.ensure_schema(con)
    found = sources.scan_directory(IMPORT_DIR)
    skipped = [p.name for p in sources.unrecognized_files(IMPORT_DIR)]
    staged = []
    for path, spec in found:
        if not file_registry.needs_import(con, path):
            continue
        n = staging.load_csv_to_staging(con, path, spec)
        file_registry.record_import(con, path, spec.dataset_type, n)
        staged.append({"file": path.name, "dataset_type": spec.dataset_type, "rows": n})
    counts = warehouse.build_warehouse(con, SCRAPED_DB)
    return {"staged": staged, "skipped_unrecognized": skipped, "warehouse": counts}
