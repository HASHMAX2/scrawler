"""Rule-based Decision Engine: given an investment profile, ranks communities
by a transparent weighted score built entirely from already-computed metrics
(yield, PSF growth as an appreciation proxy, liquidity score, oversupply risk
penalty). This is NOT financial advice and NOT a forecast — every score
component and weight is returned alongside the ranking so the "why" is
always inspectable, per the product's decision-support (not black-box)
requirement.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from apps.api.analytics.core import estimated_gross_yield, liquidity_score, oversupply_risk, pct_change, resolve_period, weighted_score
from apps.api.db import db

router = APIRouter()

MIN_SALES_OR_RENTAL_SAMPLE = 10

PRIORITY_WEIGHTS = {
    "rental_income": {"yield": 0.6, "appreciation": 0.1, "liquidity": 0.3},
    "capital_appreciation": {"yield": 0.1, "appreciation": 0.6, "liquidity": 0.3},
    "liquidity": {"yield": 0.2, "appreciation": 0.2, "liquidity": 0.6},
    "balanced": {"yield": 0.34, "appreciation": 0.33, "liquidity": 0.33},
}

RISK_PENALTY_MULTIPLIER = {"low": 1.5, "medium": 1.0, "high": 0.5}
OVERSUPPLY_PENALTY_BASE = {"very_high": 40, "high": 20, "moderate": 5, "low": 0, "insufficient_data": 0}


def _yield_score(yield_pct: float | None) -> float | None:
    if yield_pct is None:
        return None
    return max(0.0, min(100.0, (yield_pct / 15.0) * 100))


def _appreciation_score(psf_growth_pct: float | None) -> float | None:
    if psf_growth_pct is None:
        return None
    clipped = max(-20.0, min(20.0, psf_growth_pct))
    return ((clipped + 20.0) / 40.0) * 100


@router.get("")
def decision_engine(
    period: str = "180d",
    budget_max: float | None = None,
    areas: str | None = Query(None, description="Comma-separated community_key values to restrict to"),
    property_type: str | None = None,
    bedroom: str | None = None,
    ready_offplan: str = "either",  # ready | offplan | either
    priority: str = "balanced",  # rental_income | capital_appreciation | liquidity | balanced
    risk_tolerance: str = "medium",  # low | medium | high
    limit: int = 10,
    con=Depends(db),
):
    window = resolve_period(con, period)
    weights = PRIORITY_WEIGHTS.get(priority, PRIORITY_WEIGHTS["balanced"])
    risk_mult = RISK_PENALTY_MULTIPLIER.get(risk_tolerance, 1.0)

    sales_filters = ["fs.instance_date BETWEEN ? AND ?", "fs.group_en = 'Sales'"]
    sales_params: list = [window.current_start, window.current_end]
    if property_type:
        sales_filters.append("fs.canonical_property_type = ?")
        sales_params.append(property_type)
    if bedroom:
        sales_filters.append("fs.canonical_bedroom = ?")
        sales_params.append(bedroom)
    if ready_offplan == "ready":
        sales_filters.append("fs.is_offplan = false")
    elif ready_offplan == "offplan":
        sales_filters.append("fs.is_offplan = true")
    if budget_max is not None:
        sales_filters.append("fs.trans_value_aed <= ?")
        sales_params.append(budget_max)
    if areas:
        keys = [a.strip() for a in areas.split(",") if a.strip()]
        placeholders = ", ".join(["?"] * len(keys))
        sales_filters.append(f"da.community_key IN ({placeholders})")
        sales_params.extend(keys)
    sales_where = " AND ".join(sales_filters)

    rental_filters = ["fr.registration_date BETWEEN ? AND ?"]
    rental_params: list = [window.current_start, window.current_end]
    if property_type:
        rental_filters.append("fr.canonical_property_type = ?")
        rental_params.append(property_type)
    if bedroom:
        rental_filters.append("fr.canonical_bedroom = ?")
        rental_params.append(bedroom)
    if areas:
        keys = [a.strip() for a in areas.split(",") if a.strip()]
        placeholders = ", ".join(["?"] * len(keys))
        rental_filters.append(f"da.community_key IN ({placeholders})")
        rental_params.extend(keys)
    rental_where = " AND ".join(rental_filters)

    sales_rows = con.execute(
        f"""
        SELECT da.community_key, da.community_name, count(*) c, median(fs.trans_value_aed) mp, median(fs.price_per_sqft_aed) psf
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE {sales_where}
        GROUP BY 1, 2
        """,
        sales_params,
    ).fetchall()
    rental_rows = con.execute(
        f"""
        SELECT da.community_key, count(*) c, median(fr.annual_amount_aed) mr
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE {rental_where}
        GROUP BY 1
        """,
        rental_params,
    ).fetchall()
    rental_by_key = {ck: (c, mr) for ck, c, mr in rental_rows}

    # Reuses the same WHERE clause text (placeholders are positional, not
    # named) with the date range swapped to the previous period — every
    # other filter (property type, bedroom, offplan, budget, areas) stays
    # identical so the PSF comparison is apples-to-apples.
    prev_psf_rows = con.execute(
        f"""
        SELECT da.community_key, median(fs.price_per_sqft_aed)
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE {sales_where}
        GROUP BY 1
        """,
        [window.previous_start, window.previous_end] + sales_params[2:],
    ).fetchall()
    prev_psf_by_key = dict(prev_psf_rows)

    candidates = []
    excluded_insufficient_data = 0
    for ck, name, sales_count, median_price, median_psf in sales_rows:
        rental_count, median_rent = rental_by_key.get(ck, (0, None))
        if sales_count < MIN_SALES_OR_RENTAL_SAMPLE and rental_count < MIN_SALES_OR_RENTAL_SAMPLE:
            excluded_insufficient_data += 1
            continue
        candidates.append({
            "community_key": ck, "community_name": name,
            "sales_count": sales_count, "median_price": median_price, "median_psf": median_psf,
            "rental_count": rental_count, "median_rent": median_rent,
            "prev_psf": prev_psf_by_key.get(ck),
        })

    active_months_rows = con.execute(
        f"""
        SELECT da.community_key, count(DISTINCT date_trunc('month', fs.instance_date))
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE {sales_where}
        GROUP BY 1
        """,
        sales_params,
    ).fetchall()
    active_months_by_key = dict(active_months_rows)
    months_span = max(1.0, ((window.current_end - window.current_start).days + 1) / 30.44)

    supply_rows = con.execute(
        """
        SELECT da.community_key, sum(us.total_units)
        FROM scraped.unit_supply us
        JOIN scraped.developments d ON us.development_id = d.id
        JOIN dim_area da ON da.scraped_area_id = d.area_id
        WHERE d.normalized_status IN ('under_construction', 'planned', 'announced')
        GROUP BY 1
        """
    ).fetchall()
    supply_by_key = dict(supply_rows)

    days = (window.current_end - window.current_start).days + 1
    results = []
    for c in candidates:
        yield_pct = estimated_gross_yield(c["median_rent"], c["median_price"])
        psf_growth = pct_change(c["median_psf"], c["prev_psf"])

        active_months = active_months_by_key.get(c["community_key"], 0)
        consistency = min(1.0, active_months / months_span) if months_span > 0 else 0.0
        liquidity = liquidity_score(c["sales_count"], months_span, consistency)

        incoming_units = supply_by_key.get(c["community_key"])
        trailing_annualized = round((c["sales_count"] + c["rental_count"]) * 365 / days, 0) if days > 0 else None
        risk = oversupply_risk(incoming_units, trailing_annualized)

        y_score = _yield_score(yield_pct)
        a_score = _appreciation_score(psf_growth)
        l_score = liquidity["score"]

        components = {"yield": y_score, "appreciation": a_score, "liquidity": l_score}
        base_score = weighted_score(components, weights)
        if base_score is None:
            continue

        penalty = OVERSUPPLY_PENALTY_BASE.get(risk["risk"], 0) * risk_mult
        final_score = round(max(0.0, min(100.0, base_score - penalty)), 1)

        risks = []
        missing_data = []
        if incoming_units is None:
            missing_data.append("No scraped supply data for this community")
        if yield_pct is None:
            missing_data.append("Insufficient rental+sales sample to estimate yield")
        if psf_growth is None:
            missing_data.append("Insufficient sample to estimate price momentum")
        if risk["risk"] in ("high", "very_high"):
            risks.append(f"Oversupply risk: {risk['risk']} (incoming {incoming_units:,} units vs ~{int(risk['trailing_annualized_demand'] or 0):,} annualized demand)")
        if c["sales_count"] < 30 or c["rental_count"] < 30:
            risks.append(f"Small sample this period (sales={c['sales_count']}, rentals={c['rental_count']}) — treat metrics as indicative, not precise")

        why_parts = []
        if y_score is not None:
            why_parts.append(f"estimated yield {yield_pct:.1f}%")
        if a_score is not None:
            why_parts.append(f"PSF {'up' if psf_growth >= 0 else 'down'} {abs(psf_growth):.1f}% vs previous period")
        why_parts.append(f"liquidity score {l_score:.0f}/100 ({c['sales_count']} sales over {months_span:.1f} months)")
        why = f"Ranked on {priority.replace('_', ' ')} priority: " + ", ".join(why_parts) + "."

        results.append({
            "community_key": c["community_key"], "community_name": c["community_name"],
            "median_price": c["median_price"], "median_rent": c["median_rent"],
            "estimated_gross_yield_pct": yield_pct, "psf_growth_pct": psf_growth,
            "sales_count": c["sales_count"], "rental_count": c["rental_count"],
            "liquidity": liquidity, "oversupply_risk": risk,
            "score": final_score,
            "score_breakdown": {"components": components, "weights": weights, "oversupply_penalty": round(penalty, 1)},
            "why": why, "risks": risks, "missing_data": missing_data,
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    return {
        "period": window.label,
        "profile": {
            "budget_max": budget_max, "areas": areas, "property_type": property_type, "bedroom": bedroom,
            "ready_offplan": ready_offplan, "priority": priority, "risk_tolerance": risk_tolerance,
        },
        "methodology": (
            "Deterministic weighted score from already-calculated metrics (estimated gross yield, PSF growth as a capital-appreciation "
            "proxy, and a transparent liquidity score), minus a penalty when scraped supply data indicates high/very-high oversupply risk. "
            "This is NOT financial advice, NOT a price forecast, and communities with fewer than "
            f"{MIN_SALES_OR_RENTAL_SAMPLE} observations this period are excluded ({excluded_insufficient_data} excluded)."
        ),
        "excluded_insufficient_data": excluded_insufficient_data,
        "results": results[:limit],
    }
