"""Market Pulse: fastest growing/cooling areas, hot projects, rental
hotspots, and developer momentum — the "what changed" companion to the
Overview page's "what is" snapshot. Every figure is a period-over-period
comparison computed directly from fact_sales/fact_rentals; nothing here is
a forecast.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import momentum_direction, pct_change, resolve_period
from apps.api.db import db

router = APIRouter()

MIN_SAMPLE = 10
MIN_PROJECT_SAMPLE = 5
HOT_PROJECT_RATIO = 2.0
# A trailing baseline under ~1 sale/month makes the ratio unstable (a jump
# from 0.05 -> 3/month reads as "6000% hot" but is really just a project
# with almost no prior sales history) — floor the baseline before dividing.
MIN_BASELINE_MONTHLY = 1.0


def _area_growth(con, metric_table: str, date_col: str, extra_where: str, start, end, prev_start, prev_end):
    rows = con.execute(
        f"""
        WITH cur AS (
            SELECT da.community_key, da.community_name, count(*) c, median(m.{"trans_value_aed" if metric_table == "fact_sales" else "annual_amount_aed"}) mv
            FROM {metric_table} m JOIN dim_area da ON m.area_id = da.area_id
            WHERE m.{date_col} BETWEEN ? AND ? {extra_where}
            GROUP BY 1, 2
        ), prev AS (
            SELECT da.community_key, count(*) c
            FROM {metric_table} m JOIN dim_area da ON m.area_id = da.area_id
            WHERE m.{date_col} BETWEEN ? AND ? {extra_where}
            GROUP BY 1
        )
        SELECT cur.community_key, cur.community_name, cur.c, COALESCE(prev.c, 0), cur.mv
        FROM cur LEFT JOIN prev ON cur.community_key = prev.community_key
        WHERE cur.c >= ?
        """,
        [start, end, prev_start, prev_end, MIN_SAMPLE],
    ).fetchall()
    out = []
    for ck, name, cur_c, prev_c, median_value in rows:
        change = pct_change(cur_c, prev_c)
        if change is None:
            continue
        out.append({
            "community_key": ck, "community_name": name,
            "current_count": cur_c, "previous_count": prev_c,
            "change_pct": change, "median_value": median_value,
            "momentum": momentum_direction(change),
        })
    return out


@router.get("")
def pulse(period: str = "90d", limit: int = 5, con=Depends(db)):
    window = resolve_period(con, period)
    args = (window.current_start, window.current_end, window.previous_start, window.previous_end)

    sales_growth = _area_growth(con, "fact_sales", "instance_date", "AND m.group_en = 'Sales'", *args)
    rentals_growth = _area_growth(con, "fact_rentals", "registration_date", "", *args)

    fastest_growing = sorted(sales_growth, key=lambda x: x["change_pct"], reverse=True)[:limit]
    cooling = sorted([x for x in sales_growth if x["change_pct"] < 0], key=lambda x: x["change_pct"])[:limit]
    rental_hotspots = sorted(rentals_growth, key=lambda x: x["change_pct"], reverse=True)[:limit]

    hot_projects_rows = con.execute(
        """
        WITH cur AS (
            SELECT project_id, count(*) c FROM fact_sales
            WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' AND project_id IS NOT NULL
            GROUP BY 1
        ), baseline AS (
            -- trailing 6-month monthly average, EXCLUDING the current window, per project
            SELECT project_id, count(*) / 6.0 AS monthly_avg FROM fact_sales
            WHERE instance_date BETWEEN (CAST(? AS DATE) - INTERVAL 6 MONTH) AND (CAST(? AS DATE) - INTERVAL 1 DAY)
              AND group_en = 'Sales' AND project_id IS NOT NULL
            GROUP BY 1
        )
        SELECT dp.dld_project_name, cur.c, baseline.monthly_avg
        FROM cur
        JOIN baseline ON cur.project_id = baseline.project_id
        JOIN dim_project dp ON cur.project_id = dp.project_id
        WHERE cur.c >= ? AND baseline.monthly_avg > 0
        ORDER BY (cur.c / baseline.monthly_avg) DESC
        LIMIT ?
        """,
        [window.current_start, window.current_end, window.current_start, window.current_start, MIN_PROJECT_SAMPLE, limit * 3],
    ).fetchall()
    hot_projects = []
    for name, cur_c, monthly_avg in hot_projects_rows:
        if monthly_avg < MIN_BASELINE_MONTHLY:
            continue
        ratio = round(cur_c / monthly_avg, 2)
        if ratio >= HOT_PROJECT_RATIO:
            hot_projects.append({"project_name": name, "current_count": cur_c, "trailing_monthly_avg": round(monthly_avg, 1), "ratio": ratio})
    hot_projects = sorted(hot_projects, key=lambda x: x["ratio"], reverse=True)[:limit]

    developer_momentum_rows = con.execute(
        """
        WITH cur AS (
            SELECT d.developer_id, count(*) c FROM fact_sales fs
            JOIN dim_project dp ON fs.project_id = dp.project_id
            JOIN scraped.developments d ON dp.matched_development_id = d.id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
            GROUP BY 1
        ), prev AS (
            SELECT d.developer_id, count(*) c FROM fact_sales fs
            JOIN dim_project dp ON fs.project_id = dp.project_id
            JOIN scraped.developments d ON dp.matched_development_id = d.id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
            GROUP BY 1
        )
        SELECT dev.name, cur.c, COALESCE(prev.c, 0)
        FROM cur
        JOIN scraped.developers dev ON cur.developer_id = dev.id
        LEFT JOIN prev ON cur.developer_id = prev.developer_id
        WHERE cur.c >= ?
        """,
        [window.current_start, window.current_end, window.previous_start, window.previous_end, MIN_PROJECT_SAMPLE],
    ).fetchall()
    developer_momentum = []
    for name, cur_c, prev_c in developer_momentum_rows:
        change = pct_change(cur_c, prev_c)
        if change is not None:
            developer_momentum.append({"developer_name": name, "current_count": cur_c, "previous_count": prev_c, "change_pct": change})
    developer_momentum = sorted(developer_momentum, key=lambda x: x["change_pct"], reverse=True)[:limit]

    return {
        "period": window.label,
        "min_sample": MIN_SAMPLE,
        "fastest_growing_areas": fastest_growing,
        "cooling_areas": cooling,
        "hot_projects": hot_projects,
        "rental_hotspots": rental_hotspots,
        "developer_momentum": developer_momentum,
    }
