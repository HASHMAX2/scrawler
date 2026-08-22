from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import (
    data_max_date,
    data_min_date,
    estimated_gross_yield,
    format_aed,
    pct_change,
    resolve_period,
    with_confidence,
)
from apps.api.db import db

router = APIRouter()


def _sales_kpis(con, start, end, community_key=None):
    where = "instance_date BETWEEN ? AND ? AND group_en='Sales'"
    params = [start, end]
    if community_key:
        where += " AND area_id IN (SELECT area_id FROM dim_area WHERE community_key = ?)"
        params.append(community_key)
    count, value, avg_price, median_price, median_psf = con.execute(
        f"SELECT count(*), sum(trans_value_aed), avg(trans_value_aed), median(trans_value_aed), median(price_per_sqft_aed) FROM fact_sales WHERE {where}",
        params,
    ).fetchone()
    return {"count": count or 0, "value": value, "avg_price": avg_price, "median_price": median_price, "median_psf": median_psf}


def _rental_kpis(con, start, end, community_key=None):
    where = "registration_date BETWEEN ? AND ?"
    params = [start, end]
    if community_key:
        where += " AND area_id IN (SELECT area_id FROM dim_area WHERE community_key = ?)"
        params.append(community_key)
    count, avg_rent, median_rent = con.execute(
        f"SELECT count(*), avg(annual_amount_aed), median(annual_amount_aed) FROM fact_rentals WHERE {where}", params
    ).fetchone()
    return {"count": count or 0, "avg_rent": avg_rent, "median_rent": median_rent}


@router.get("")
def overview(period: str = "30d", community_key: str | None = None, con=Depends(db)):
    window = resolve_period(con, period)
    cur_sales = _sales_kpis(con, window.current_start, window.current_end, community_key)
    prev_sales = _sales_kpis(con, window.previous_start, window.previous_end, community_key)
    cur_rentals = _rental_kpis(con, window.current_start, window.current_end, community_key)
    prev_rentals = _rental_kpis(con, window.previous_start, window.previous_end, community_key)

    yield_est = estimated_gross_yield(cur_rentals["median_rent"], cur_sales["median_price"])

    best_selling_unit = con.execute(
        """
        SELECT canonical_bedroom, count(*) c FROM fact_sales
        WHERE instance_date BETWEEN ? AND ? AND group_en='Sales'
        GROUP BY 1 ORDER BY c DESC LIMIT 1
        """,
        [window.current_start, window.current_end],
    ).fetchone()

    top_rental_area = con.execute(
        """
        SELECT da.community_name, count(*) c FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE fr.registration_date BETWEEN ? AND ?
        GROUP BY 1 ORDER BY c DESC LIMIT 1
        """,
        [window.current_start, window.current_end],
    ).fetchone()

    growth_area = con.execute(
        """
        WITH cur AS (
            SELECT da.community_key, da.community_name, count(*) c FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en='Sales' GROUP BY 1, 2
        ), prev AS (
            SELECT da.community_key, count(*) c FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en='Sales' GROUP BY 1
        )
        SELECT cur.community_name, cur.c, COALESCE(prev.c, 0)
        FROM cur LEFT JOIN prev ON cur.community_key = prev.community_key
        WHERE cur.c >= 5
        ORDER BY (cur.c - COALESCE(prev.c, 0)) DESC LIMIT 1
        """,
        [window.current_start, window.current_end, window.previous_start, window.previous_end],
    ).fetchone()

    largest_supply = con.execute(
        """
        SELECT a.name, us.total_units FROM scraped.unit_supply us
        JOIN scraped.developments d ON us.development_id = d.id
        JOIN scraped.areas a ON d.area_id = a.id
        WHERE us.total_units IS NOT NULL ORDER BY us.total_units DESC LIMIT 1
        """
    ).fetchone()

    active_projects, under_construction = con.execute(
        "SELECT count(*), sum(normalized_status = 'under_construction') FROM scraped.developments WHERE is_active = 1"
    ).fetchone()
    known_units = con.execute("SELECT sum(total_units) FROM scraped.unit_supply").fetchone()[0]

    return {
        "period": window.label,
        "current_range": [window.current_start.isoformat(), window.current_end.isoformat()],
        "previous_range": [window.previous_start.isoformat(), window.previous_end.isoformat()],
        "data_range": [data_min_date(con).isoformat(), data_max_date(con).isoformat()],
        "sales": {
            **cur_sales,
            "value_formatted": format_aed(cur_sales["value"]),
            "avg_price_formatted": format_aed(cur_sales["avg_price"]),
            "change_pct": pct_change(cur_sales["count"], prev_sales["count"]),
            "value_change_pct": pct_change(cur_sales["value"], prev_sales["value"]),
            "confidence": with_confidence(cur_sales["count"]),
        },
        "rentals": {
            **cur_rentals,
            "change_pct": pct_change(cur_rentals["count"], prev_rentals["count"]),
            "confidence": with_confidence(cur_rentals["count"]),
        },
        "estimated_gross_yield_pct": yield_est,
        "best_selling_unit_type": {"bedroom": best_selling_unit[0], "count": best_selling_unit[1]} if best_selling_unit else None,
        "highest_rental_activity_area": {"community": top_rental_area[0], "count": top_rental_area[1]} if top_rental_area else None,
        "highest_transaction_growth_area": (
            {"community": growth_area[0], "current": growth_area[1], "previous": growth_area[2], "change_pct": pct_change(growth_area[1], growth_area[2])}
            if growth_area else None
        ),
        "largest_incoming_supply": {"area": largest_supply[0], "units": largest_supply[1]} if largest_supply else None,
        "supply": {
            "active_projects": active_projects,
            "under_construction": under_construction,
            "known_residential_units": known_units,
        },
    }
