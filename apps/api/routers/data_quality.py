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

    scraped_cross_check = _scraped_transaction_cross_check(con)

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
        "scraped_cross_check": scraped_cross_check,
    }


def _scraped_transaction_cross_check(con) -> dict:
    """Propsearch's own scraped `transactions` table (4,039 rows, independent
    of the DLD bulk CSVs) sat completely unused. It's a second, independent
    sample of the same underlying sale events — a free cross-check on our
    DLD-derived fact_sales, not a replacement for it (its sample is far
    smaller). Compares per-project median price and transaction count for
    every project with matched scraped transactions, so large disagreements
    are visible rather than silently trusted.
    """
    total_scraped = con.execute("SELECT count(*) FROM scraped.transactions").fetchone()[0]
    matched = con.execute("SELECT count(*) FROM scraped.transactions WHERE development_id IS NOT NULL").fetchone()[0]
    with_dld_counterpart = con.execute(
        """
        SELECT count(DISTINCT t.development_id) FROM scraped.transactions t
        JOIN dim_project dp ON dp.matched_development_id = t.development_id
        WHERE t.development_id IS NOT NULL
        """
    ).fetchone()[0]

    rows = con.execute(
        """
        WITH scraped_agg AS (
            SELECT t.development_id, count(*) c, median(t.price_aed) med_price
            FROM scraped.transactions t
            WHERE t.development_id IS NOT NULL AND t.price_aed IS NOT NULL
            GROUP BY 1
            HAVING count(*) >= 2
        )
        SELECT d.name, sa.c, sa.med_price, dld.c, dld.med_price
        FROM scraped_agg sa
        JOIN scraped.developments d ON sa.development_id = d.id
        LEFT JOIN (
            SELECT dp.matched_development_id AS development_id, count(*) c, median(fs.trans_value_aed) med_price
            FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
            WHERE dp.matched_development_id IS NOT NULL AND fs.group_en = 'Sales'
            GROUP BY 1
        ) dld ON sa.development_id = dld.development_id
        ORDER BY (dld.c IS NOT NULL) DESC, sa.c DESC
        LIMIT 30
        """
    ).fetchall()

    items = []
    for name, scraped_count, scraped_median, dld_count, dld_median in rows:
        price_diff_pct = None
        if scraped_median and dld_median:
            price_diff_pct = round((scraped_median - dld_median) / dld_median * 100, 1)
        items.append({
            "development_name": name,
            "scraped_transaction_count": scraped_count,
            "scraped_median_price": scraped_median,
            "dld_transaction_count": dld_count or 0,
            "dld_median_price": dld_median,
            "median_price_diff_pct": price_diff_pct,
        })

    return {
        "total_scraped_transactions": total_scraped,
        "matched_to_development": matched,
        "developments_with_dld_counterpart": with_dld_counterpart,
        "projects_compared": items,
        "note": (
            "Propsearch scrapes only a small recent sample per project page (max observed: 2 per development here), so this is "
            "directional, not statistically powered. Most scraped developments also have no DLD-side project match yet (entity "
            "resolution gap, not a data error) — rows with a DLD counterpart are sorted first; rows below them show scraped-only figures."
        ),
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
