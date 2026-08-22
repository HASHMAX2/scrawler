from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.db import db

router = APIRouter()


@router.get("")
def supply(con=Depends(db)):
    status_breakdown = con.execute(
        "SELECT COALESCE(normalized_status, 'unknown'), count(*) FROM scraped.developments WHERE is_active = 1 GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()

    known_units = con.execute(
        "SELECT sum(total_units), sum(residential_units), sum(studios), sum(beds_1), sum(beds_2), sum(beds_3), sum(beds_4), sum(beds_5_plus), sum(villas), sum(townhouses) FROM scraped.unit_supply"
    ).fetchone()
    unit_supply_populated = con.execute("SELECT count(*) FROM scraped.unit_supply").fetchone()[0]

    by_area = con.execute(
        """
        SELECT a.name, count(*) projects, sum(d.total_units)
        FROM scraped.developments d LEFT JOIN scraped.areas a ON d.area_id = a.id
        WHERE d.is_active = 1 AND d.normalized_status IN ('under_construction', 'planned', 'announced')
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """
    ).fetchall()

    by_developer = con.execute(
        """
        SELECT dev.name, count(*) FROM scraped.developments d
        JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE d.is_active = 1 AND d.normalized_status IN ('under_construction', 'planned', 'announced')
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """
    ).fetchall()

    return {
        "status_breakdown": {s: c for s, c in status_breakdown},
        "unit_supply_populated_developments": unit_supply_populated,
        "known_units": {
            "total": known_units[0], "residential": known_units[1], "studios": known_units[2],
            "1br": known_units[3], "2br": known_units[4], "3br": known_units[5], "4br": known_units[6],
            "5br_plus": known_units[7], "villas": known_units[8], "townhouses": known_units[9],
        } if unit_supply_populated > 0 else None,
        "upcoming_by_area": [{"area": a, "projects": p, "units": u} for a, p, u in by_area],
        "upcoming_by_developer": [{"developer": d, "projects": p} for d, p in by_developer],
    }
