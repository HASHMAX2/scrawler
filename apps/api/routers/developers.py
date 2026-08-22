from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import market_share, resolve_period
from apps.api.db import db

router = APIRouter()


@router.get("")
def list_developers(period: str = "180d", limit: int = 50, con=Depends(db)):
    window = resolve_period(con, period)
    rows = con.execute(
        """
        WITH s AS (
            SELECT dp.matched_development_id, count(*) c, sum(fs.trans_value_aed) v
            FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
            WHERE dp.matched_development_id IS NOT NULL AND fs.instance_date BETWEEN ? AND ? AND fs.group_en='Sales'
            GROUP BY 1
        )
        SELECT dev.id, dev.name, count(DISTINCT d.id) project_count, COALESCE(sum(s.c), 0), COALESCE(sum(s.v), 0)
        FROM scraped.developers dev
        JOIN scraped.developments d ON d.developer_id = dev.id
        LEFT JOIN s ON s.matched_development_id = d.id
        GROUP BY 1, 2 ORDER BY sum(s.c) DESC NULLS LAST LIMIT ?
        """,
        [window.current_start, window.current_end, limit],
    ).fetchall()
    total = sum(r[3] for r in rows) or 1
    return {
        "period": window.label,
        "items": [
            {"developer_id": r[0], "name": r[1], "project_count": r[2], "sales_count": r[3], "sales_value": r[4], "market_share_pct": market_share(r[3], total)}
            for r in rows
        ],
    }
