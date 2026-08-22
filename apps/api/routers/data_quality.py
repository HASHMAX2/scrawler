from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.db import db
from ingestion.normalize import canonical_key

router = APIRouter()


@router.get("")
def data_quality_summary(con=Depends(db)):
    area_confidence = con.execute("SELECT match_confidence, count(*) FROM dim_area GROUP BY 1").fetchall()
    project_confidence = con.execute("SELECT match_confidence, count(*) FROM dim_project GROUP BY 1").fetchall()

    file_registry = con.execute(
        "SELECT file_path, dataset_type, row_count, imported_at, status FROM file_registry ORDER BY imported_at DESC"
    ).fetchall()

    unmatched_sales = con.execute(
        "SELECT count(*) FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id WHERE dp.matched_development_id IS NULL AND dp.dld_project_name IS NOT NULL"
    ).fetchone()[0]
    unmatched_rentals = con.execute(
        "SELECT count(*) FROM fact_rentals fr JOIN dim_project dp ON fr.project_id = dp.project_id WHERE dp.matched_development_id IS NULL AND dp.dld_project_name IS NOT NULL"
    ).fetchone()[0]

    missing_project_sales = con.execute("SELECT count(*) FROM fact_sales WHERE project_id IS NULL").fetchone()[0]
    missing_project_rentals = con.execute("SELECT count(*) FROM fact_rentals WHERE project_id IS NULL").fetchone()[0]

    invalid_price = con.execute("SELECT count(*) FROM fact_sales WHERE trans_value_aed IS NULL OR trans_value_aed <= 0").fetchone()[0]
    invalid_rent = con.execute("SELECT count(*) FROM fact_rentals WHERE annual_amount_aed IS NULL OR annual_amount_aed <= 0").fetchone()[0]

    hierarchy_methods = con.execute("SELECT grouping_method, count(*) FROM dim_project WHERE grouping_method IS NOT NULL GROUP BY 1").fetchall()
    needs_review_count = con.execute("SELECT count(*) FROM dim_master_project WHERE needs_review").fetchone()[0]
    master_project_count = con.execute("SELECT count(*) FROM dim_master_project").fetchone()[0]
    multi_building_count = con.execute("SELECT count(*) FROM dim_master_project WHERE building_count > 1").fetchone()[0]

    return {
        "area_match_confidence": {c: n for c, n in area_confidence},
        "project_match_confidence": {c: n for c, n in project_confidence},
        "files_imported": [
            {"file_path": p, "dataset_type": t, "row_count": r, "imported_at": ts.isoformat() if ts else None, "status": s}
            for p, t, r, ts, s in file_registry
        ],
        "unmatched_project_sales_rows": unmatched_sales,
        "unmatched_project_rental_rows": unmatched_rentals,
        "missing_project_sales_rows": missing_project_sales,
        "missing_project_rental_rows": missing_project_rentals,
        "invalid_price_rows": invalid_price,
        "invalid_rent_rows": invalid_rent,
        "project_hierarchy": {
            "master_project_count": master_project_count,
            "multi_building_master_count": multi_building_count,
            "needs_review_count": needs_review_count,
            "grouping_method_breakdown": {m: n for m, n in hierarchy_methods},
        },
    }


@router.get("/review-queue")
def review_queue(entity_type: str = "area", limit: int = 100, con=Depends(db)):
    if entity_type == "area":
        rows = con.execute(
            """
            SELECT canonical_key, dld_area_name, match_score
            FROM dim_area WHERE match_confidence = 'fuzzy_low'
            ORDER BY match_score DESC LIMIT ?
            """,
            [limit],
        ).fetchall()
    else:
        rows = con.execute(
            """
            SELECT canonical_key, dld_project_name, match_score
            FROM dim_project WHERE match_confidence = 'fuzzy_low'
            ORDER BY match_score DESC LIMIT ?
            """,
            [limit],
        ).fetchall()
    return {"entity_type": entity_type, "items": [{"raw_key": k, "raw_name": n, "match_score": s} for k, n, s in rows]}


class ResolveRequest(BaseModel):
    raw_name: str
    entity_type: str  # 'area' | 'project'
    resolved_entity_id: int | None
    note: str | None = None


@router.post("/resolve")
def resolve_entity(body: ResolveRequest, con=Depends(db)):
    con.execute(
        """
        INSERT INTO entity_alias_overrides (raw_key, entity_type, resolved_entity_id, resolved_by, resolved_at, note)
        VALUES (?, ?, ?, 'user', ?, ?)
        ON CONFLICT (raw_key, entity_type) DO UPDATE SET
            resolved_entity_id = excluded.resolved_entity_id,
            resolved_by = excluded.resolved_by,
            resolved_at = excluded.resolved_at,
            note = excluded.note
        """,
        [canonical_key(body.raw_name), body.entity_type, body.resolved_entity_id, datetime.now(timezone.utc), body.note],
    )
    return {"status": "saved", "note": "Re-run the ingestion refresh for this override to take effect in dim_area/dim_project."}


@router.get("/project-hierarchy")
def project_hierarchy_review(limit: int = 100, con=Depends(db)):
    """Master projects flagged for manual review: any family formed via the
    lower-confidence hyphen-split rule, or a prior manual override — never
    silently trusted, always inspectable here.
    """
    rows = con.execute(
        """
        SELECT mp.master_project_id, mp.display_name, mp.slug, mp.building_count,
               list(dp.dld_project_name ORDER BY dp.dld_project_name), list(dp.grouping_method ORDER BY dp.dld_project_name)
        FROM dim_master_project mp
        JOIN dim_project dp ON dp.master_project_id = mp.master_project_id
        WHERE mp.needs_review
        GROUP BY 1, 2, 3, 4
        ORDER BY mp.building_count DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    return {
        "items": [
            {"master_project_id": r[0], "display_name": r[1], "slug": r[2], "building_count": r[3], "buildings": list(zip(r[4], r[5]))}
            for r in rows
        ]
    }


class MasterProjectResolveRequest(BaseModel):
    raw_project_name: str  # the building's own raw DLD project name
    override_master_key: str  # canonical key of the master project it should belong to (use its own canonical name to split it out standalone)
    note: str | None = None


@router.post("/resolve-master-project")
def resolve_master_project(body: MasterProjectResolveRequest, con=Depends(db)):
    con.execute(
        """
        INSERT INTO master_project_overrides (raw_project_canonical_key, override_master_key, resolved_by, resolved_at, note)
        VALUES (?, ?, 'user', ?, ?)
        ON CONFLICT (raw_project_canonical_key) DO UPDATE SET
            override_master_key = excluded.override_master_key,
            resolved_at = excluded.resolved_at,
            note = excluded.note
        """,
        [canonical_key(body.raw_project_name), canonical_key(body.override_master_key), datetime.now(timezone.utc), body.note],
    )
    return {"status": "saved", "note": "Re-run the ingestion refresh for this override to take effect in dim_master_project."}
