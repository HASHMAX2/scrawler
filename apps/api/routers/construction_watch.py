from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.db import db

router = APIRouter()

# Only these field changes are genuine re-crawl signal. change_log also
# records 'record'/'is_active'/'storeys_raw'/'developer_raw' noise from the
# initial bulk-insert pass (change_kind='new_record') and cosmetic re-scrapes
# — excluded so this feed reads as real construction news, not crawler diffs.
WATCHED_FIELDS = [
    "normalized_status", "raw_status", "estimated_completion_date",
    "actual_completion_date", "total_units",
]


@router.get("")
def construction_watch(field: str | None = None, limit: int = 50, con=Depends(db)):
    where = "cl.entity_type = 'development' AND cl.change_kind = 'field_changed' AND cl.field_name IN ({})".format(
        ", ".join(["?"] * len(WATCHED_FIELDS))
    )
    params: list = list(WATCHED_FIELDS)
    if field and field in WATCHED_FIELDS:
        where = "cl.entity_type = 'development' AND cl.change_kind = 'field_changed' AND cl.field_name = ?"
        params = [field]

    rows = con.execute(
        f"""
        SELECT cl.id, cl.entity_id, d.name, a.name, cl.field_name, cl.old_value, cl.new_value, cl.detected_at,
               dp.master_project_id, mp.slug
        FROM scraped.change_log cl
        JOIN scraped.developments d ON cl.entity_id = d.id
        LEFT JOIN scraped.areas a ON d.area_id = a.id
        LEFT JOIN dim_project dp ON dp.matched_development_id = d.id
        LEFT JOIN dim_master_project mp ON dp.master_project_id = mp.master_project_id
        WHERE {where}
        ORDER BY cl.detected_at DESC
        LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    field_counts = con.execute(
        f"""
        SELECT cl.field_name, count(*) FROM scraped.change_log cl
        WHERE cl.entity_type = 'development' AND cl.change_kind = 'field_changed'
          AND cl.field_name IN ({", ".join(["?"] * len(WATCHED_FIELDS))})
        GROUP BY 1
        """,
        WATCHED_FIELDS,
    ).fetchall()

    flipped_to_completed = con.execute(
        """
        SELECT count(*) FROM scraped.change_log cl
        WHERE cl.entity_type = 'development' AND cl.change_kind = 'field_changed'
          AND cl.field_name = 'normalized_status' AND cl.new_value = 'completed'
        """
    ).fetchone()[0]

    return {
        "items": [
            {
                "change_id": r[0], "development_id": r[1], "development_name": r[2], "area_name": r[3],
                "field_name": r[4], "old_value": r[5], "new_value": r[6], "detected_at": r[7],
                "master_project_slug": r[9],
            }
            for r in rows
        ],
        "field_counts": {f: n for f, n in field_counts},
        "flipped_to_completed_total": flipped_to_completed,
        "watched_fields": WATCHED_FIELDS,
    }
