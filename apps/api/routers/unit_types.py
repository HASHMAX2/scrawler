from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import estimated_gross_yield, market_share, pct_change, resolve_period, with_confidence
from apps.api.db import db

router = APIRouter()

BEDROOMS = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR+", "Unknown", "Other"]


@router.get("")
def unit_types(period: str = "90d", community_key: str | None = None, con=Depends(db)):
    window = resolve_period(con, period)

    sales_where = "fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'"
    prev_sales_where = "fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'"
    rent_where = "fr.registration_date BETWEEN ? AND ?"
    sales_params: list = [window.current_start, window.current_end]
    prev_sales_params: list = [window.previous_start, window.previous_end]
    rent_params: list = [window.current_start, window.current_end]
    if community_key:
        sales_where += " AND da.community_key = ?"
        prev_sales_where += " AND da.community_key = ?"
        rent_where += " AND da.community_key = ?"
        sales_params.append(community_key)
        prev_sales_params.append(community_key)
        rent_params.append(community_key)

    sales_rows = con.execute(
        f"""
        SELECT fs.canonical_bedroom, count(*) c, median(fs.trans_value_aed) mp, median(fs.price_per_sqft_aed) psf
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE {sales_where} GROUP BY 1
        """,
        sales_params,
    ).fetchall()
    prev_sales_rows = con.execute(
        f"SELECT fs.canonical_bedroom, count(*) c FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id WHERE {prev_sales_where} GROUP BY 1",
        prev_sales_params,
    ).fetchall()
    rent_rows = con.execute(
        f"""
        SELECT fr.canonical_bedroom, count(*) c, median(fr.annual_amount_aed) mr
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE {rent_where} GROUP BY 1
        """,
        rent_params,
    ).fetchall()

    sales_by_bed = {b: {"count": c, "median_price": mp, "median_psf": psf} for b, c, mp, psf in sales_rows}
    prev_sales_by_bed = {b: c for b, c in prev_sales_rows}
    rent_by_bed = {b: {"count": c, "median_rent": mr} for b, c, mr in rent_rows}

    total_sales = sum(v["count"] for v in sales_by_bed.values()) or 1
    total_rentals = sum(v["count"] for v in rent_by_bed.values()) or 1

    items = []
    for b in BEDROOMS:
        s = sales_by_bed.get(b, {"count": 0, "median_price": None, "median_psf": None})
        r = rent_by_bed.get(b, {"count": 0, "median_rent": None})
        if s["count"] == 0 and r["count"] == 0:
            continue
        items.append({
            "bedroom": b,
            "sales_count": s["count"],
            "sales_share_pct": market_share(s["count"], total_sales),
            "sales_change_pct": pct_change(s["count"], prev_sales_by_bed.get(b, 0)),
            "median_price": s["median_price"],
            "median_psf": s["median_psf"],
            "rental_count": r["count"],
            "rental_share_pct": market_share(r["count"], total_rentals),
            "median_rent": r["median_rent"],
            "estimated_gross_yield_pct": estimated_gross_yield(r["median_rent"], s["median_price"]),
            "sales_confidence": with_confidence(s["count"]),
            "rental_confidence": with_confidence(r["count"]),
        })

    items.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)
    return {"period": window.label, "community_key": community_key, "items": items}
