from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import market_share, resolve_period
from apps.api.db import db

router = APIRouter()

_BREAKDOWN_DIMENSIONS = {
    "community": "da.community_name",
    "developer": "COALESCE(dev.name, 'Unknown')",
    "property_type": "fs.canonical_property_type",
    "bedroom": "fs.canonical_bedroom",
    "offplan": "CASE WHEN fs.is_offplan THEN 'Off-Plan' ELSE 'Ready' END",
    "project": "dp.dld_project_name",
}


@router.get("/breakdown")
def sales_breakdown(by: str = "community", period: str = "90d", community_key: str | None = None, limit: int = 20, con=Depends(db)):
    window = resolve_period(con, period)
    dim = _BREAKDOWN_DIMENSIONS.get(by, _BREAKDOWN_DIMENSIONS["community"])
    where = "fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'"
    params: list = [window.current_start, window.current_end]
    if community_key:
        where += " AND da.community_key = ?"
        params.append(community_key)

    rows = con.execute(
        f"""
        SELECT {dim} AS label, count(*) c, sum(fs.trans_value_aed) v, median(fs.trans_value_aed) mp, median(fs.price_per_sqft_aed) psf
        FROM fact_sales fs
        JOIN dim_area da ON fs.area_id = da.area_id
        LEFT JOIN dim_project dp ON fs.project_id = dp.project_id
        LEFT JOIN scraped.developments d ON dp.matched_development_id = d.id
        LEFT JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE {where} AND {dim} IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    total = sum(r[1] for r in rows)
    return {
        "period": window.label, "by": by,
        "items": [
            {"label": r[0], "count": r[1], "value": r[2], "median_price": r[3], "median_psf": r[4], "share_pct": market_share(r[1], total)}
            for r in rows
        ],
    }


@router.get("/trend")
def sales_trend(period: str = "6m", granularity: str = "week", community_key: str | None = None, con=Depends(db)):
    window = resolve_period(con, period)
    bucket = {"day": "day", "week": "week", "month": "month"}.get(granularity, "week")
    where = "instance_date BETWEEN ? AND ? AND group_en = 'Sales'"
    params: list = [window.current_start, window.current_end]
    if community_key:
        where += " AND area_id IN (SELECT area_id FROM dim_area WHERE community_key = ?)"
        params.append(community_key)

    rows = con.execute(
        f"""
        SELECT date_trunc('{bucket}', instance_date) AS bucket, count(*) c, sum(trans_value_aed) v, median(trans_value_aed) mp, median(price_per_sqft_aed) psf
        FROM fact_sales WHERE {where}
        GROUP BY 1 ORDER BY 1
        """,
        params,
    ).fetchall()
    return {
        "period": window.label, "granularity": granularity,
        "points": [{"date": r[0].isoformat(), "count": r[1], "value": r[2], "median_price": r[3], "median_psf": r[4]} for r in rows],
    }
