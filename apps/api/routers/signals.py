"""Deterministic Market Signals: human-readable observations generated from
already-calculated results, never from an LLM. Every sentence in the
response carries the exact numbers it was built from (`evidence`), so a
signal can always be traced back to the data that produced it.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import estimated_gross_yield, oversupply_risk, pct_change, resolve_period
from apps.api.db import db

router = APIRouter()

MIN_SAMPLE = 15
DOMINANT_SHARE_THRESHOLD = 35.0
RENTAL_GROWTH_THRESHOLD = 20.0
HOT_PROJECT_RATIO = 2.0
MIN_BASELINE_MONTHLY = 1.0
RENT_GROWTH_THRESHOLD = 8.0
PSF_FLAT_BAND = 3.0


@router.get("")
def signals(period: str = "90d", limit_per_category: int = 5, con=Depends(db)):
    window = resolve_period(con, period)
    out: list[dict] = []

    # 1. Dominant bedroom share of rental activity per community.
    rows = con.execute(
        """
        WITH totals AS (
            SELECT da.community_key, da.community_name, count(*) total
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? GROUP BY 1, 2
        ), by_bed AS (
            SELECT da.community_key, fr.canonical_bedroom, count(*) c
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? AND fr.canonical_bedroom NOT IN ('Unknown', 'Other')
            GROUP BY 1, 2
        )
        SELECT t.community_name, t.community_key, b.canonical_bedroom, b.c, t.total
        FROM by_bed b JOIN totals t ON b.community_key = t.community_key
        WHERE t.total >= ?
        ORDER BY (b.c * 1.0 / t.total) DESC
        """,
        [window.current_start, window.current_end, window.current_start, window.current_end, MIN_SAMPLE],
    ).fetchall()
    count = 0
    for name, community_key, bedroom, c, total in rows:
        share = round(100 * c / total, 1)
        if share < DOMINANT_SHARE_THRESHOLD:
            continue
        out.append({
            "category": "dominant_unit_demand",
            "text": f"{bedroom} apartments accounted for {share}% of rental contracts in {name} over the last {window.label}.",
            "evidence": {"community": name, "community_key": community_key, "bedroom": bedroom, "count": c, "total": total, "share_pct": share},
        })
        count += 1
        if count >= limit_per_category:
            break

    # 2. Rental activity growth per community.
    growth_rows = con.execute(
        """
        WITH cur AS (
            SELECT da.community_key, da.community_name, count(*) c
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? GROUP BY 1, 2
        ), prev AS (
            SELECT da.community_key, count(*) c
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? GROUP BY 1
        )
        SELECT cur.community_name, cur.community_key, cur.c, COALESCE(prev.c, 0)
        FROM cur LEFT JOIN prev ON cur.community_key = prev.community_key
        WHERE cur.c >= ?
        """,
        [window.current_start, window.current_end, window.previous_start, window.previous_end, MIN_SAMPLE],
    ).fetchall()
    scored = []
    for name, community_key, cur_c, prev_c in growth_rows:
        change = pct_change(cur_c, prev_c)
        if change is not None and change >= RENTAL_GROWTH_THRESHOLD:
            scored.append((change, name, community_key, cur_c, prev_c))
    for change, name, community_key, cur_c, prev_c in sorted(scored, reverse=True)[:limit_per_category]:
        out.append({
            "category": "rental_activity_growth",
            "text": f"Rental activity in {name} increased {change:.0f}% compared with the previous {window.label} period.",
            "evidence": {"community": name, "community_key": community_key, "current_count": cur_c, "previous_count": prev_c, "change_pct": change},
        })

    # 3. Project momentum (current period vs trailing 6-month monthly average).
    project_rows = con.execute(
        """
        WITH cur AS (
            SELECT project_id, count(*) c FROM fact_sales
            WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' AND project_id IS NOT NULL
            GROUP BY 1
        ), baseline AS (
            SELECT project_id, count(*) / 6.0 AS monthly_avg FROM fact_sales
            WHERE instance_date BETWEEN (CAST(? AS DATE) - INTERVAL 6 MONTH) AND (CAST(? AS DATE) - INTERVAL 1 DAY)
              AND group_en = 'Sales' AND project_id IS NOT NULL
            GROUP BY 1
        )
        SELECT dp.dld_project_name, cur.c, baseline.monthly_avg
        FROM cur JOIN baseline ON cur.project_id = baseline.project_id
        JOIN dim_project dp ON cur.project_id = dp.project_id
        WHERE cur.c >= 5 AND baseline.monthly_avg > 0
        ORDER BY (cur.c / baseline.monthly_avg) DESC
        LIMIT ?
        """,
        [window.current_start, window.current_end, window.current_start, window.current_start, limit_per_category * 3],
    ).fetchall()
    added = 0
    for name, cur_c, monthly_avg in project_rows:
        if monthly_avg < MIN_BASELINE_MONTHLY:
            continue
        ratio = round(cur_c / monthly_avg, 1)
        if ratio < HOT_PROJECT_RATIO:
            continue
        period_word = "period" if window.label not in ("30d",) else "month"
        out.append({
            "category": "project_momentum",
            "text": f"{name} recorded {cur_c} transactions this {period_word}, {ratio}x its six-month monthly average.",
            "evidence": {"project": name, "current_count": cur_c, "trailing_monthly_avg": round(monthly_avg, 1), "ratio": ratio},
        })
        added += 1
        if added >= limit_per_category:
            break

    # 4. Rent growth outpacing flat PSF, by community + bedroom.
    rent_vs_psf = con.execute(
        """
        WITH cur_rent AS (
            SELECT da.community_key, da.community_name, fr.canonical_bedroom, median(fr.annual_amount_aed) mr, count(*) c
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? AND fr.canonical_bedroom NOT IN ('Unknown', 'Other')
            GROUP BY 1, 2, 3
        ), prev_rent AS (
            SELECT da.community_key, fr.canonical_bedroom, median(fr.annual_amount_aed) mr, count(*) c
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? AND fr.canonical_bedroom NOT IN ('Unknown', 'Other')
            GROUP BY 1, 2
        ), cur_psf AS (
            SELECT da.community_key, median(fs.price_per_sqft_aed) mp
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' GROUP BY 1
        ), prev_psf AS (
            SELECT da.community_key, median(fs.price_per_sqft_aed) mp
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' GROUP BY 1
        )
        SELECT cur_rent.community_name, cur_rent.community_key, cur_rent.canonical_bedroom, cur_rent.mr, prev_rent.mr, cur_rent.c, prev_rent.c,
               cur_psf.mp, prev_psf.mp
        FROM cur_rent
        JOIN prev_rent ON cur_rent.community_key = prev_rent.community_key AND cur_rent.canonical_bedroom = prev_rent.canonical_bedroom
        JOIN cur_psf ON cur_rent.community_key = cur_psf.community_key
        JOIN prev_psf ON cur_rent.community_key = prev_psf.community_key
        WHERE cur_rent.c >= 10 AND prev_rent.c >= 10
        """,
        [
            window.current_start, window.current_end, window.previous_start, window.previous_end,
            window.current_start, window.current_end, window.previous_start, window.previous_end,
        ],
    ).fetchall()
    scored2 = []
    for name, community_key, bedroom, cur_rent, prev_rent, cur_c, prev_c, cur_psf, prev_psf in rent_vs_psf:
        rent_change = pct_change(cur_rent, prev_rent)
        psf_change = pct_change(cur_psf, prev_psf)
        if rent_change is None or psf_change is None:
            continue
        if rent_change >= RENT_GROWTH_THRESHOLD and abs(psf_change) <= PSF_FLAT_BAND:
            scored2.append((rent_change, name, community_key, bedroom, rent_change, psf_change))
    for rent_change, name, community_key, bedroom, rc, pc in sorted(scored2, reverse=True)[:limit_per_category]:
        out.append({
            "category": "rent_growth_flat_price",
            "text": f"Average rent for {bedroom} apartments in {name} rose {rc:.1f}% while transaction PSF remained broadly unchanged ({pc:+.1f}%).",
            "evidence": {"community": name, "community_key": community_key, "bedroom": bedroom, "rent_change_pct": rc, "psf_change_pct": pc},
        })

    # 5. Supply vs demand imbalance (only where a scraped profile exists).
    supply_rows = con.execute(
        """
        SELECT a.name, us_sum.units, da.community_key
        FROM scraped.areas a
        JOIN (
            SELECT d.area_id, sum(us.total_units) units FROM scraped.unit_supply us
            JOIN scraped.developments d ON us.development_id = d.id
            WHERE d.normalized_status IN ('under_construction', 'planned', 'announced')
            GROUP BY 1
        ) us_sum ON us_sum.area_id = a.id
        JOIN dim_area da ON da.scraped_area_id = a.id
        WHERE us_sum.units > 0
        """
    ).fetchall()
    days = (window.current_end - window.current_start).days + 1
    added5 = 0
    for area_name, incoming_units, community_key in supply_rows:
        rentals_count = con.execute(
            "SELECT count(*) FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id WHERE da.community_key = ? AND fr.registration_date BETWEEN ? AND ?",
            [community_key, window.current_start, window.current_end],
        ).fetchone()[0]
        annualized = round(rentals_count * 365 / days, 0) if days > 0 else 0
        risk = oversupply_risk(incoming_units, annualized)
        if risk["risk"] in ("high", "very_high"):
            out.append({
                "category": "supply_demand_imbalance",
                "text": f"{area_name} has approximately {int(incoming_units):,} units scheduled for future delivery relative to only {int(annualized):,} observed annualized rental contracts.",
                "evidence": {"area": area_name, "community_key": community_key, "incoming_units": incoming_units, "annualized_rental_demand": annualized, "risk": risk["risk"], "ratio": risk["ratio"]},
            })
            added5 += 1
            if added5 >= limit_per_category:
                break

    return {"period": window.label, "min_sample": MIN_SAMPLE, "signals": out}
