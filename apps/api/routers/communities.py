from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.analytics.core import estimated_gross_yield, market_share, oversupply_risk, resolve_period, with_confidence
from apps.api.db import db

router = APIRouter()


@router.get("")
def list_communities(
    period: str = "90d",
    sort: str = "sales_count",
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    con=Depends(db),
):
    window = resolve_period(con, period)
    sort_columns = {
        "sales_count": "sales_count",
        "sales_value": "sales_value",
        "rental_count": "rental_count",
        "median_price": "median_price",
        "median_rent": "median_rent",
    }
    order_col = sort_columns.get(sort, "sales_count")

    search_clause = ""
    params: list = [window.current_start, window.current_end, window.current_start, window.current_end]
    if search:
        search_clause = "WHERE n.community_name ILIKE ?"
        params.append(f"%{search}%")

    total_clause = "WHERE community_name ILIKE ?" if search else ""
    total = con.execute(
        f"SELECT count(DISTINCT community_key) FROM dim_area {total_clause}",
        [f"%{search}%"] if search else [],
    ).fetchone()[0]

    rows = con.execute(
        f"""
        WITH s AS (
            SELECT da.community_key, count(*) sales_count, sum(fs.trans_value_aed) sales_value,
                   median(fs.trans_value_aed) median_price, median(fs.price_per_sqft_aed) median_psf
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
            GROUP BY 1
        ), r AS (
            SELECT da.community_key, count(*) rental_count, median(fr.annual_amount_aed) median_rent
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ?
            GROUP BY 1
        ), names AS (
            SELECT DISTINCT community_key, community_name, scraped_area_id FROM dim_area
        )
        SELECT n.community_key, n.community_name, n.scraped_area_id,
               COALESCE(s.sales_count, 0) sales_count, s.sales_value, s.median_price, s.median_psf,
               COALESCE(r.rental_count, 0) rental_count, r.median_rent
        FROM names n
        LEFT JOIN s ON n.community_key = s.community_key
        LEFT JOIN r ON n.community_key = r.community_key
        {search_clause}
        ORDER BY {order_col} DESC NULLS LAST
        LIMIT ? OFFSET ?
        """,
        params + [page_size, (page - 1) * page_size],
    ).fetchall()

    items = []
    for r in rows:
        items.append({
            "community_key": r[0],
            "community_name": r[1],
            "has_scraped_profile": r[2] is not None,
            "sales_count": r[3],
            "sales_value": r[4],
            "median_price": r[5],
            "median_psf": r[6],
            "rental_count": r[7],
            "median_rent": r[8],
            "estimated_gross_yield_pct": estimated_gross_yield(r[8], r[5]),
        })

    return {"period": window.label, "page": page, "page_size": page_size, "total": total, "items": items}


@router.get("/{community_key}")
def community_detail(community_key: str, period: str = "90d", con=Depends(db)):
    window = resolve_period(con, period)

    name_row = con.execute(
        "SELECT community_name, scraped_area_id FROM dim_area WHERE community_key = ? LIMIT 1", [community_key]
    ).fetchone()
    if not name_row:
        raise HTTPException(404, "Unknown community_key")
    community_name, scraped_area_id = name_row

    sales_summary = con.execute(
        """
        SELECT count(*), sum(fs.trans_value_aed), median(fs.trans_value_aed), median(fs.price_per_sqft_aed)
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        """,
        [community_key, window.current_start, window.current_end],
    ).fetchone()

    rental_summary = con.execute(
        """
        SELECT count(*), median(fr.annual_amount_aed), sum(fr.is_renewal), sum(NOT fr.is_renewal)
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE da.community_key = ? AND fr.registration_date BETWEEN ? AND ?
        """,
        [community_key, window.current_start, window.current_end],
    ).fetchone()

    bedroom_sales = con.execute(
        """
        SELECT fs.canonical_bedroom, count(*) c FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        GROUP BY 1 ORDER BY c DESC
        """,
        [community_key, window.current_start, window.current_end],
    ).fetchall()
    total_sales_for_share = sum(c for _, c in bedroom_sales) or 1

    bedroom_rentals = con.execute(
        """
        SELECT fr.canonical_bedroom, count(*) c, median(fr.annual_amount_aed)
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE da.community_key = ? AND fr.registration_date BETWEEN ? AND ?
        GROUP BY 1 ORDER BY c DESC
        """,
        [community_key, window.current_start, window.current_end],
    ).fetchall()
    total_rentals_for_share = sum(c for _, c, _ in bedroom_rentals) or 1

    top_projects = con.execute(
        """
        SELECT dp.dld_project_name, count(*) c, sum(fs.trans_value_aed)
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id JOIN dim_project dp ON fs.project_id = dp.project_id
        WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND dp.dld_project_name IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT 10
        """,
        [community_key, window.current_start, window.current_end],
    ).fetchall()

    top_developers = []
    upcoming_supply = None
    if scraped_area_id is not None:
        top_developers = con.execute(
            """
            SELECT dev.name, count(*) c FROM scraped.developments d
            JOIN scraped.developers dev ON d.developer_id = dev.id
            WHERE d.area_id = ? GROUP BY 1 ORDER BY c DESC LIMIT 10
            """,
            [scraped_area_id],
        ).fetchall()
        upcoming_supply = con.execute(
            """
            SELECT sum(us.total_units) FROM scraped.unit_supply us
            JOIN scraped.developments d ON us.development_id = d.id
            WHERE d.area_id = ? AND d.normalized_status IN ('under_construction', 'planned', 'announced')
            """,
            [scraped_area_id],
        ).fetchone()[0]

    yield_est = estimated_gross_yield(rental_summary[1], sales_summary[2])

    days = (window.current_end - window.current_start).days + 1
    trailing_annualized_demand = round((sales_summary[0] + rental_summary[0]) * 365 / days, 0) if days > 0 else None
    supply_risk = oversupply_risk(upcoming_supply, trailing_annualized_demand)

    return {
        "community_key": community_key,
        "community_name": community_name,
        "has_scraped_profile": scraped_area_id is not None,
        "period": window.label,
        "sales": {
            "count": sales_summary[0], "value": sales_summary[1], "median_price": sales_summary[2],
            "median_psf": sales_summary[3], "confidence": with_confidence(sales_summary[0]),
        },
        "rentals": {
            "count": rental_summary[0], "median_rent": rental_summary[1],
            "renewals": rental_summary[2], "new_contracts": rental_summary[3],
            "confidence": with_confidence(rental_summary[0]),
        },
        "estimated_gross_yield_pct": yield_est,
        "bedroom_demand": {
            "sales": [{"bedroom": b, "count": c, "share_pct": market_share(c, total_sales_for_share)} for b, c in bedroom_sales],
            "rentals": [
                {"bedroom": b, "count": c, "share_pct": market_share(c, total_rentals_for_share), "median_rent": mr}
                for b, c, mr in bedroom_rentals
            ],
        },
        "top_projects": [{"name": n, "sales_count": c, "sales_value": v} for n, c, v in top_projects],
        "top_developers": [{"name": n, "project_count": c} for n, c in top_developers],
        "upcoming_supply_units": upcoming_supply,
        "oversupply_risk": supply_risk,
    }
