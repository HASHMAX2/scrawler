from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from apps.api.analytics.core import (
    estimated_gross_yield,
    liquidity_score,
    market_share,
    momentum_direction,
    pct_change,
    resolve_period,
    with_confidence,
)
from apps.api.db import db

router = APIRouter()


@router.get("")
def list_projects(search: str | None = None, period: str = "90d", limit: int = 50, con=Depends(db)):
    window = resolve_period(con, period)
    where = "dp.dld_project_name IS NOT NULL"
    params: list = []
    if search:
        where += " AND dp.dld_project_name ILIKE ?"
        params.append(f"%{search}%")

    rows = con.execute(
        f"""
        WITH s AS (
            SELECT project_id, count(*) c, sum(trans_value_aed) v FROM fact_sales
            WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' GROUP BY 1
        ), r AS (
            SELECT project_id, count(*) c FROM fact_rentals
            WHERE registration_date BETWEEN ? AND ? GROUP BY 1
        )
        SELECT dp.project_id, dp.dld_project_name, dp.matched_development_id, dev.name,
               COALESCE(s.c, 0), s.v, COALESCE(r.c, 0), dp.building_slug, mp.slug, d.hero_image_url
        FROM dim_project dp
        LEFT JOIN dim_master_project mp ON dp.master_project_id = mp.master_project_id
        LEFT JOIN s ON dp.project_id = s.project_id
        LEFT JOIN r ON dp.project_id = r.project_id
        LEFT JOIN scraped.developments d ON dp.matched_development_id = d.id
        LEFT JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE {where}
        ORDER BY COALESCE(s.c, 0) + COALESCE(r.c, 0) DESC
        LIMIT ?
        """,
        [window.current_start, window.current_end, window.current_start, window.current_end] + params + [limit],
    ).fetchall()

    return {
        "period": window.label,
        "items": [
            {
                "project_id": r[0], "name": r[1], "matched_development_id": r[2], "developer_name": r[3],
                "sales_count": r[4], "sales_value": r[5], "rental_count": r[6],
                "building_slug": r[7], "master_slug": r[8], "hero_image_url": r[9],
            }
            for r in rows
        ],
    }


@router.get("/{project_id}")
def project_detail(project_id: int, period: str = "180d", con=Depends(db)):
    window = resolve_period(con, period)
    proj = con.execute(
        "SELECT dld_project_name, dld_master_project_name, matched_development_id, matched_building_id, match_confidence FROM dim_project WHERE project_id = ?",
        [project_id],
    ).fetchone()
    if not proj:
        raise HTTPException(404, "Unknown project_id")
    name, master_name, matched_development_id, matched_building_id, confidence = proj

    sales = con.execute(
        "SELECT count(*), sum(trans_value_aed), median(trans_value_aed), median(price_per_sqft_aed) FROM fact_sales WHERE project_id = ? AND instance_date BETWEEN ? AND ? AND group_en='Sales'",
        [project_id, window.current_start, window.current_end],
    ).fetchone()
    rentals = con.execute(
        "SELECT count(*), median(annual_amount_aed) FROM fact_rentals WHERE project_id = ? AND registration_date BETWEEN ? AND ?",
        [project_id, window.current_start, window.current_end],
    ).fetchone()

    scraped_profile = None
    if matched_development_id is not None:
        row = con.execute(
            """
            SELECT d.name, d.normalized_status, d.total_units, d.estimated_completion_date, dev.name, a.name
            FROM scraped.developments d
            LEFT JOIN scraped.developers dev ON d.developer_id = dev.id
            LEFT JOIN scraped.areas a ON d.area_id = a.id
            WHERE d.id = ?
            """,
            [matched_development_id],
        ).fetchone()
        if row:
            scraped_profile = {
                "name": row[0], "status": row[1], "total_units": row[2],
                "estimated_completion_date": row[3], "developer_name": row[4], "area_name": row[5],
            }

    months_span = max(1.0, ((window.current_end - window.current_start).days + 1) / 30.44)
    active_months = con.execute(
        "SELECT count(DISTINCT date_trunc('month', instance_date)) FROM fact_sales WHERE project_id = ? AND instance_date BETWEEN ? AND ? AND group_en = 'Sales'",
        [project_id, window.current_start, window.current_end],
    ).fetchone()[0]
    consistency = min(1.0, active_months / months_span) if months_span > 0 else 0.0
    liquidity = liquidity_score(sales[0], months_span, consistency)

    return {
        "project_id": project_id,
        "name": name,
        "master_project_name": master_name,
        "match_confidence": confidence,
        "scraped_profile": scraped_profile,
        "period": window.label,
        "sales": {"count": sales[0], "value": sales[1], "median_price": sales[2], "median_psf": sales[3], "confidence": with_confidence(sales[0])},
        "rentals": {"count": rentals[0], "median_rent": rentals[1], "confidence": with_confidence(rentals[0])},
        "estimated_gross_yield_pct": estimated_gross_yield(rentals[1], sales[2]),
        "liquidity": liquidity,
    }


BEDROOMS = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR+", "Other", "Unknown"]


def _scope_clause(scope_ids: list[int], unit_type: str | None, transaction_type: str | None, is_sales: bool) -> tuple[str, list]:
    """Shared WHERE-clause builder for both the sales and rentals side of the
    Project Intelligence payload, so building/unit-type/transaction-type
    filters stay consistent across every section of the page.
    """
    placeholders = ", ".join(["?"] * len(scope_ids))
    clauses = [f"project_id IN ({placeholders})"]
    params: list = list(scope_ids)
    if unit_type:
        clauses.append("canonical_bedroom = ?")
        params.append(unit_type)
    if is_sales:
        clauses.append("group_en = 'Sales'")
        if transaction_type == "offplan":
            clauses.append("is_offplan = true")
        elif transaction_type == "ready":
            clauses.append("is_offplan = false")
    return " AND ".join(clauses), params


MILESTONE_ORDER = {
    "First Trace": 0, "Estimated Start": 1, "Construction Started": 2,
    "Revised Est. Completion": 3, "Estimated Completion": 3, "Construction Finished": 4,
}


def _scraped_enrichment(con, development_id: int, building_name: str | None) -> dict:
    """Pulls the rich Propsearch-scraped profile for one development: facts,
    developer/architect/contractor, construction milestones, dated progress
    updates, and photo documents. Queried directly off the attached `scraped`
    SQLite db — no warehouse rebuild needed, these tables were already there.
    """
    dev = con.execute(
        """
        SELECT d.name, d.building_type_raw, d.raw_status, d.normalized_status, d.storeys_raw,
               d.total_units, d.total_units_raw, d.project_value_aed, d.project_value_usd,
               d.official_website, d.plot_reference, d.overview_text, d.construction_start_date,
               d.estimated_completion_date, d.actual_completion_date, d.first_trace_date,
               d.hero_image_url, d.latitude, d.longitude, d.is_multi_building
        FROM scraped.developments d WHERE d.id = ?
        """,
        [development_id],
    ).fetchone()
    if not dev:
        return None

    companies = con.execute(
        """
        SELECT role, company_name, company_url FROM scraped.construction_history
        WHERE development_id = ?
        ORDER BY CASE role WHEN 'Developer' THEN 0 WHEN 'Architect' THEN 1 WHEN 'Contractor' THEN 2 ELSE 3 END
        """,
        [development_id],
    ).fetchall()

    milestones_raw = con.execute(
        "SELECT label, date_raw, date_parsed FROM scraped.construction_milestones WHERE development_id = ?",
        [development_id],
    ).fetchall()
    milestones = sorted(
        ({"label": label, "date_raw": date_raw, "date_parsed": date_parsed} for label, date_raw, date_parsed in milestones_raw),
        key=lambda m: MILESTONE_ORDER.get(m["label"], 99),
    )

    updates = con.execute(
        """
        SELECT DISTINCT date_raw, date_parsed, description FROM scraped.construction_updates
        WHERE development_id = ? ORDER BY date_parsed DESC NULLS LAST, date_raw DESC LIMIT 15
        """,
        [development_id],
    ).fetchall()

    # Each re-crawl inserts a fresh snapshot row per doc_type (a growing photo
    # gallery gets a new row over time, not an update to the old one) — take
    # only the most-recently-seen snapshot per doc_type, or photo counts and
    # cover images would be summed/duplicated across crawl history.
    doc_rows = con.execute(
        """
        SELECT doc_type, photo_count, photo_urls_json FROM scraped.documents
        WHERE development_id = ?
        QUALIFY row_number() OVER (PARTITION BY doc_type ORDER BY last_seen DESC) = 1
        """,
        [development_id],
    ).fetchall()
    docs_by_type: dict[str, dict] = {}
    for doc_type, photo_count, photo_urls_json in doc_rows:
        bucket = docs_by_type.setdefault(doc_type, {"doc_type": doc_type, "total_photos": 0, "cover_photo_urls": []})
        bucket["total_photos"] += photo_count or 0
        if len(bucket["cover_photo_urls"]) < 3 and photo_urls_json:
            try:
                urls = json.loads(photo_urls_json)
            except (TypeError, ValueError):
                urls = []
            for u in urls:
                if len(bucket["cover_photo_urls"]) >= 3:
                    break
                bucket["cover_photo_urls"].append(u)

    (name, building_type, raw_status, normalized_status, storeys, total_units, total_units_raw,
     project_value_aed, project_value_usd, official_website, plot_reference, overview_text,
     construction_start_date, estimated_completion_date, actual_completion_date, first_trace_date,
     hero_image_url, latitude, longitude, is_multi_building) = dev

    return {
        "source_development_id": development_id,
        "source_building_name": building_name or name,
        "hero_image_url": hero_image_url,
        "building_type": building_type,
        "status": normalized_status,
        "raw_status": raw_status,
        "storeys": storeys,
        "total_units": total_units,
        "total_units_raw": total_units_raw,
        "project_value_aed": project_value_aed,
        "project_value_usd": project_value_usd,
        "official_website": official_website,
        "plot_reference": plot_reference,
        "overview_text": overview_text,
        "construction_start_date": construction_start_date,
        "estimated_completion_date": estimated_completion_date,
        "actual_completion_date": actual_completion_date,
        "first_trace_date": first_trace_date,
        "latitude": latitude,
        "longitude": longitude,
        "is_multi_building": bool(is_multi_building),
        "companies": [{"role": r, "name": n, "url": u} for r, n, u in companies],
        "milestones": milestones,
        "updates": [{"date_raw": dr, "date_parsed": dp, "description": desc} for dr, dp, desc in updates],
        "documents": sorted(docs_by_type.values(), key=lambda d: d["doc_type"]),
    }


@router.get("/master/{slug}")
def master_project_detail(
    slug: str,
    period: str = "90d",
    building_slug: str | None = None,
    unit_type: str | None = None,
    transaction_type: str | None = None,  # 'offplan' | 'ready' | None (either)
    con=Depends(db),
):
    master = con.execute(
        "SELECT master_project_id, display_name, developer_name, area_name, building_count, needs_review FROM dim_master_project WHERE slug = ?",
        [slug],
    ).fetchone()
    if not master:
        raise HTTPException(404, "Unknown project slug")
    master_id, display_name, developer_name, area_name, building_count, needs_review = master

    buildings = con.execute(
        """
        SELECT project_id, dld_project_name, building_label, building_slug, grouping_method, matched_development_id
        FROM dim_project WHERE master_project_id = ? ORDER BY dld_project_name
        """,
        [master_id],
    ).fetchall()
    if not buildings:
        raise HTTPException(404, "Master project has no linked buildings")

    selected_building = None
    if building_slug:
        match = next((b for b in buildings if b[3] == building_slug), None)
        if not match:
            raise HTTPException(404, "Unknown building_slug for this project")
        scope_ids = [match[0]]
        selected_building = {"project_id": match[0], "name": match[1].strip(), "building_label": match[2], "slug": match[3]}
    else:
        scope_ids = [b[0] for b in buildings]

    window = resolve_period(con, period)
    sales_where, sales_params = _scope_clause(scope_ids, unit_type, transaction_type, is_sales=True)
    rentals_where, rentals_params = _scope_clause(scope_ids, unit_type, None, is_sales=False)

    def _sales_stats(start, end):
        return con.execute(
            f"""SELECT count(*), sum(trans_value_aed), avg(trans_value_aed), median(trans_value_aed),
                       avg(price_per_sqft_aed), median(price_per_sqft_aed)
                FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ?""",
            sales_params + [start, end],
        ).fetchone()

    def _rental_stats(start, end):
        return con.execute(
            f"""SELECT count(*), avg(annual_amount_aed), median(annual_amount_aed), avg(rent_per_sqft_aed),
                       sum(NOT is_renewal), sum(is_renewal)
                FROM fact_rentals WHERE {rentals_where} AND registration_date BETWEEN ? AND ?""",
            rentals_params + [start, end],
        ).fetchone()

    cur_sales = _sales_stats(window.current_start, window.current_end)
    prev_sales = _sales_stats(window.previous_start, window.previous_end)
    cur_rentals = _rental_stats(window.current_start, window.current_end)
    prev_rentals = _rental_stats(window.previous_start, window.previous_end)

    anchor = window.current_end
    count_30d = con.execute(
        f"SELECT count(*) FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ?",
        sales_params + [anchor - timedelta(days=29), anchor],
    ).fetchone()[0]
    count_90d = con.execute(
        f"SELECT count(*) FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ?",
        sales_params + [anchor - timedelta(days=89), anchor],
    ).fetchone()[0]
    count_6m = con.execute(
        f"SELECT count(*) FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ?",
        sales_params + [anchor - timedelta(days=181), anchor],
    ).fetchone()[0]

    period_days = max(1, (window.current_end - window.current_start).days + 1)
    sales_velocity = round(cur_sales[0] / period_days, 3)
    rental_velocity = round(cur_rentals[0] / period_days, 3)
    price_trend_pct = pct_change(cur_sales[3], prev_sales[3])
    rental_trend_pct = pct_change(cur_rentals[2], prev_rentals[2])

    months_span = max(1.0, period_days / 30.44)
    active_months = con.execute(
        f"SELECT count(DISTINCT date_trunc('month', instance_date)) FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ?",
        sales_params + [window.current_start, window.current_end],
    ).fetchone()[0]
    consistency = min(1.0, active_months / months_span) if months_span > 0 else 0.0
    liquidity = liquidity_score(cur_sales[0], months_span, consistency)

    # Trend series (weekly), respecting the same scope/filters.
    sales_trend = con.execute(
        f"""SELECT date_trunc('week', instance_date) d, count(*), sum(trans_value_aed), avg(price_per_sqft_aed), avg(trans_value_aed)
            FROM fact_sales WHERE {sales_where} AND instance_date BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""",
        sales_params + [window.current_start, window.current_end],
    ).fetchall()
    rentals_trend = con.execute(
        f"""SELECT date_trunc('week', registration_date) d, count(*), avg(annual_amount_aed), avg(rent_per_sqft_aed)
            FROM fact_rentals WHERE {rentals_where} AND registration_date BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""",
        rentals_params + [window.current_start, window.current_end],
    ).fetchall()

    # Unit-type performance (this section itself IS the breakdown, so it
    # ignores the unit_type filter but still respects building/transaction_type).
    ut_sales_where, ut_sales_params = _scope_clause(scope_ids, None, transaction_type, is_sales=True)
    ut_rentals_where, ut_rentals_params = _scope_clause(scope_ids, None, None, is_sales=False)
    ut_sales = {
        r[0]: r[1:] for r in con.execute(
            f"""SELECT canonical_bedroom, count(*), sum(trans_value_aed), avg(trans_value_aed), median(trans_value_aed), avg(price_per_sqft_aed)
                FROM fact_sales WHERE {ut_sales_where} AND instance_date BETWEEN ? AND ? GROUP BY 1""",
            ut_sales_params + [window.current_start, window.current_end],
        ).fetchall()
    }
    ut_rentals = {
        r[0]: r[1:] for r in con.execute(
            f"""SELECT canonical_bedroom, count(*), avg(annual_amount_aed), median(annual_amount_aed)
                FROM fact_rentals WHERE {ut_rentals_where} AND registration_date BETWEEN ? AND ? GROUP BY 1""",
            ut_rentals_params + [window.current_start, window.current_end],
        ).fetchall()
    }
    unit_type_performance = []
    for bedroom in BEDROOMS:
        s = ut_sales.get(bedroom)
        r = ut_rentals.get(bedroom)
        if not s and not r:
            continue
        s = s or (0, None, None, None, None)
        r = r or (0, None, None)
        unit_type_performance.append({
            "bedroom": bedroom,
            "sales_count": s[0], "sales_value": s[1], "avg_price": s[2], "median_price": s[3], "avg_psf": s[4],
            "rental_count": r[0], "avg_rent": r[1], "median_rent": r[2],
            "estimated_gross_yield_pct": estimated_gross_yield(r[2], s[3]),
        })
    unit_type_performance.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)

    # Building comparison table: every building in the family, regardless of
    # the building_slug scope above, filtered by unit_type/transaction_type.
    bp_sales_where, bp_sales_params = _scope_clause([b[0] for b in buildings], unit_type, transaction_type, is_sales=True)
    bp_rentals_where, bp_rentals_params = _scope_clause([b[0] for b in buildings], unit_type, None, is_sales=False)
    bp_sales = {
        r[0]: r[1:] for r in con.execute(
            f"""SELECT project_id, count(*), sum(trans_value_aed), avg(trans_value_aed), avg(price_per_sqft_aed), max(instance_date)
                FROM fact_sales WHERE {bp_sales_where} AND instance_date BETWEEN ? AND ? GROUP BY 1""",
            bp_sales_params + [window.current_start, window.current_end],
        ).fetchall()
    }
    bp_rentals = {
        r[0]: r[1:] for r in con.execute(
            f"""SELECT project_id, count(*), avg(annual_amount_aed), max(registration_date)
                FROM fact_rentals WHERE {bp_rentals_where} AND registration_date BETWEEN ? AND ? GROUP BY 1""",
            bp_rentals_params + [window.current_start, window.current_end],
        ).fetchall()
    }
    building_performance = []
    for project_id, raw_name, building_label, b_slug, method, matched_dev_id in buildings:
        s = bp_sales.get(project_id, (0, None, None, None, None))
        r = bp_rentals.get(project_id, (0, None, None))
        last_tx = max((d for d in (s[4], r[2]) if d is not None), default=None)
        building_performance.append({
            "project_id": project_id, "name": raw_name.strip(), "building_label": building_label, "slug": b_slug,
            "grouping_method": method, "has_scraped_profile": matched_dev_id is not None,
            "sales_count": s[0], "sales_value": s[1], "avg_price": s[2], "avg_psf": s[3],
            "rental_count": r[0], "avg_rent": r[1],
            "estimated_gross_yield_pct": estimated_gross_yield(r[1], s[2]),
            "last_transaction_date": last_tx.isoformat() if last_tx else None,
        })
    building_performance.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)

    # Sales vs rentals — every figure here is read off unit_type_performance,
    # not separately invented, so it can't disagree with the table above it.
    total_sales_for_share = sum(x["sales_count"] for x in unit_type_performance) or 1
    total_rentals_for_share = sum(x["rental_count"] for x in unit_type_performance) or 1
    most_liquid = max(unit_type_performance, key=lambda x: x["sales_count"] + x["rental_count"], default=None)
    most_rented = max((x for x in unit_type_performance if x["rental_count"] > 0), key=lambda x: x["rental_count"], default=None)
    highest_volume = max((x for x in unit_type_performance if x["sales_count"] > 0), key=lambda x: x["sales_count"], default=None)
    sales_vs_rentals = {
        "sales_demand_count": cur_sales[0],
        "rental_demand_count": cur_rentals[0],
        "rental_to_sales_ratio": round(cur_rentals[0] / cur_sales[0], 2) if cur_sales[0] else None,
        "estimated_gross_yield_pct": estimated_gross_yield(cur_rentals[2], cur_sales[3]),
        "most_liquid_unit_type": most_liquid["bedroom"] if most_liquid else None,
        "most_rented_unit_type": most_rented["bedroom"] if most_rented else None,
        "highest_volume_unit_type": highest_volume["bedroom"] if highest_volume else None,
    }

    grouping_summary: dict[str, int] = {}
    for b in buildings:
        grouping_summary[b[4]] = grouping_summary.get(b[4], 0) + 1

    if selected_building:
        profile_dev_id = match[5]
        profile_building_name = selected_building["name"]
    else:
        profile_candidate = next((b for b in buildings if b[5] is not None), None)
        profile_dev_id = profile_candidate[5] if profile_candidate else None
        profile_building_name = profile_candidate[1].strip() if profile_candidate else None
    scraped_enrichment = _scraped_enrichment(con, profile_dev_id, profile_building_name) if profile_dev_id is not None else None

    return {
        "master_project_id": master_id,
        "slug": slug,
        "name": display_name,
        "developer_name": developer_name,
        "area_name": area_name,
        "building_count": building_count,
        "needs_review": needs_review,
        "buildings": [
            {"project_id": b[0], "name": b[1].strip(), "building_label": b[2], "slug": b[3], "grouping_method": b[4]}
            for b in buildings
        ],
        "selected_building": selected_building,
        "scraped_enrichment": scraped_enrichment,
        "period": window.label,
        "filters": {"unit_type": unit_type, "transaction_type": transaction_type},
        "kpis": {
            "sales": {
                "count": cur_sales[0], "count_change_pct": pct_change(cur_sales[0], prev_sales[0]),
                "value": cur_sales[1], "avg_price": cur_sales[2], "median_price": cur_sales[3],
                "avg_psf": cur_sales[4], "median_psf": cur_sales[5],
                "count_30d": count_30d, "count_90d": count_90d, "count_6m": count_6m,
                "confidence": with_confidence(cur_sales[0]),
            },
            "rentals": {
                "count": cur_rentals[0], "count_change_pct": pct_change(cur_rentals[0], prev_rentals[0]),
                "avg_rent": cur_rentals[1], "median_rent": cur_rentals[2], "avg_rent_psf": cur_rentals[3],
                "new_count": cur_rentals[4], "renewal_count": cur_rentals[5],
                "confidence": with_confidence(cur_rentals[0]),
            },
            "market": {
                "sales_velocity_per_day": sales_velocity, "rental_velocity_per_day": rental_velocity,
                "avg_ticket_size": cur_sales[2],
                "estimated_gross_yield_pct": estimated_gross_yield(cur_rentals[2], cur_sales[3]),
                "price_trend_pct": price_trend_pct, "price_trend": momentum_direction(price_trend_pct),
                "rental_trend_pct": rental_trend_pct, "rental_trend": momentum_direction(rental_trend_pct),
                "liquidity": liquidity,
            },
        },
        "trends": {
            "sales": [{"date": r[0].isoformat(), "count": r[1], "value": r[2], "avg_psf": r[3], "avg_price": r[4]} for r in sales_trend],
            "rentals": [{"date": r[0].isoformat(), "count": r[1], "avg_rent": r[2], "avg_rent_psf": r[3]} for r in rentals_trend],
        },
        "unit_type_performance": [
            {**u, "sales_share_pct": market_share(u["sales_count"], total_sales_for_share), "rental_share_pct": market_share(u["rental_count"], total_rentals_for_share)}
            for u in unit_type_performance
        ],
        "building_performance": building_performance,
        "sales_vs_rentals": sales_vs_rentals,
        "data_quality": {
            "grouping_method_summary": grouping_summary,
            "matched_scraped_buildings": sum(1 for b in buildings if b[5] is not None),
            "total_buildings": len(buildings),
        },
    }
