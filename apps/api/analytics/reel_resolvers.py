"""The Reel Analytics Engine: reusable, parameterized query functions that
back the Reel Master Library. Per the product brief, this is intentionally
NOT 235 independent pipelines — every resolver here is one of a handful of
generic primitives (market snapshot, community comparison, yield/PSF/
liquidity ranking, developer ranking, budget explorer, project scorecard,
supply analysis, building-level insight) that many reel titles share,
parameterized differently.

Every number returned here traces to a real SQL aggregate over
fact_sales/fact_rentals/dim_project/dim_master_project/dim_area (or the
scraped project/developer/supply tables) — nothing is invented. Where a
result would need data this warehouse doesn't have, the caller (reels.py)
has already classified the reel as partial/external before a resolver is
even invoked for the missing piece.
"""
from __future__ import annotations

import duckdb

from apps.api.analytics.core import (
    estimated_gross_yield,
    liquidity_score,
    momentum_direction,
    oversupply_risk,
    pct_change,
    resolve_period,
)

MIN_SAMPLE = 5


def _metric(label: str, value, fmt: str, tone: str | None = None, note: str | None = None) -> dict:
    return {"label": label, "value": value, "format": fmt, "tone": tone, "note": note}


def _yield_tone(pct: float | None) -> str | None:
    if pct is None:
        return None
    if pct >= 7:
        return "good"
    if pct < 4:
        return "bad"
    return "neutral"


# ---------------------------------------------------------------------------
# 1. Market snapshot — category "Weekly / Monthly Market Reels" (#1-15) and
#    the generic fallback for supplementary ideas.
# ---------------------------------------------------------------------------
def market_snapshot(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)

    top_projects = con.execute(
        """
        SELECT dp.dld_project_name, count(*) c, sum(fs.trans_value_aed) v
        FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND dp.dld_project_name IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT 5
        """,
        [window.current_start, window.current_end],
    ).fetchall()

    top_communities = con.execute(
        """
        SELECT da.community_name, count(*) c, sum(fs.trans_value_aed) v
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        GROUP BY 1 ORDER BY c DESC LIMIT 5
        """,
        [window.current_start, window.current_end],
    ).fetchall()

    top_developers = con.execute(
        """
        SELECT dmp.developer_name, count(*) c, sum(fs.trans_value_aed) v
        FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
        JOIN dim_master_project dmp ON dp.master_project_id = dmp.master_project_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND dmp.developer_name IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT 5
        """,
        [window.current_start, window.current_end],
    ).fetchall()

    totals = con.execute(
        "SELECT count(*), sum(trans_value_aed) FROM fact_sales WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales'",
        [window.current_start, window.current_end],
    ).fetchone()
    offplan_split = con.execute(
        """
        SELECT is_offplan, count(*) FROM fact_sales
        WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' GROUP BY 1
        """,
        [window.current_start, window.current_end],
    ).fetchall()
    offplan_count = sum(c for is_op, c in offplan_split if is_op)
    ready_count = sum(c for is_op, c in offplan_split if not is_op)

    proptype_split = con.execute(
        """
        SELECT canonical_property_type, count(*) FROM fact_sales
        WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' GROUP BY 1 ORDER BY 2 DESC
        """,
        [window.current_start, window.current_end],
    ).fetchall()
    bedroom_split = con.execute(
        """
        SELECT canonical_bedroom, count(*) FROM fact_sales
        WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' GROUP BY 1 ORDER BY 2 DESC
        """,
        [window.current_start, window.current_end],
    ).fetchall()

    prev_total = con.execute(
        "SELECT count(*) FROM fact_sales WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales'",
        [window.previous_start, window.previous_end],
    ).fetchone()[0]
    rentals_total = con.execute(
        "SELECT count(*) FROM fact_rentals WHERE registration_date BETWEEN ? AND ?",
        [window.current_start, window.current_end],
    ).fetchone()[0]

    sales_count, sales_value = totals
    change = pct_change(sales_count, prev_total)

    entities = [{
        "id": "dubai", "label": "Dubai", "subtitle": f"Market snapshot — {window.label}",
        "metrics": [
            _metric("Transactions", sales_count, "count"),
            _metric("Transaction Value", sales_value, "aed"),
            _metric("Rental Contracts", rentals_total, "count"),
            _metric("vs Previous Period", change, "pct_signed", "good" if (change or 0) > 0 else "bad" if (change or 0) < 0 else "neutral"),
        ],
        "sampleSize": {"sales": sales_count, "rentals": rentals_total},
        "breakdown": {
            "topProjects": [{"label": n, "value": c, "secondary": v} for n, c, v in top_projects],
            "topCommunities": [{"label": n, "value": c, "secondary": v} for n, c, v in top_communities],
            "topDevelopers": [{"label": n, "value": c, "secondary": v} for n, c, v in top_developers],
            "offplanVsReady": [{"label": "Off-Plan", "value": offplan_count}, {"label": "Ready", "value": ready_count}],
            "propertyTypeSplit": [{"label": t or "Unknown", "value": c} for t, c in proptype_split],
            "bedroomSplit": [{"label": b, "value": c} for b, c in bedroom_split],
        },
    }]

    facts = []
    if top_projects:
        facts.append(f"{top_projects[0][0]} led the market with {top_projects[0][1]} recorded sales this {window.label}.")
    if top_communities:
        facts.append(f"{top_communities[0][0]} recorded the most transactions of any community ({top_communities[0][1]}).")
    if sales_count and offplan_count:
        facts.append(f"Off-plan made up {round(100*offplan_count/sales_count)}% of all sales transactions.")
    if change is not None:
        direction = "up" if change > 0 else "down"
        facts.append(f"Transaction volume is {direction} {abs(change):.0f}% versus the previous {window.label} period.")
    if bedroom_split:
        facts.append(f"{bedroom_split[0][0]} was the most-transacted unit type ({bedroom_split[0][1]} sales).")

    return {
        "question": "What happened in the Dubai property market this period?",
        "period": window.label,
        "entities": entities,
        "verdict": None,
        "reelReadyFacts": facts[:7],
        "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Six-month operational dataset — short-term trend only, not a multi-year historical comparison.",
        "sources": ["DLD-T", "DLD-R", "OWN"],
    }


# ---------------------------------------------------------------------------
# 2. Community vs community — category "Community vs Community" (#16-35),
#    also reused by myth-tests and budget/what-would-I-buy comparisons.
# ---------------------------------------------------------------------------
def _top_communities(con, window, limit=2) -> list[str]:
    rows = con.execute(
        """
        SELECT da.community_key FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        GROUP BY 1 ORDER BY count(*) DESC LIMIT ?
        """,
        [window.current_start, window.current_end, limit],
    ).fetchall()
    return [r[0] for r in rows]


def community_comparison(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    from apps.api.routers.communities import community_detail

    window = resolve_period(con, period)
    keys = [k for k in [params.get("communityA"), params.get("communityB")] if k]
    if len(keys) < 2:
        keys = _top_communities(con, window, 2)
    if len(keys) < 2:
        keys = keys + keys  # degenerate: not enough data, still don't crash

    details = [community_detail(k, period, con) for k in keys[:2]]

    entities = []
    for d in details:
        yield_pct = d["estimated_gross_yield_pct"]
        entities.append({
            "id": d["community_key"], "label": d["community_name"].upper(),
            "subtitle": f"{d['sales']['count']} sales · {d['rentals']['count']} rentals this {window.label}",
            "metrics": [
                _metric("Median Sale Price", d["sales"]["median_price"], "aed"),
                _metric("Median PSF", d["sales"]["median_psf"], "psf"),
                _metric("Median Annual Rent", d["rentals"]["median_rent"], "aed"),
                _metric("Est. Gross Yield", yield_pct, "pct", _yield_tone(yield_pct)),
                _metric("Sales (liquidity)", d["sales"]["count"], "count"),
                _metric("Rental Demand", d["rentals"]["count"], "count"),
                _metric("Upcoming Supply", d["upcoming_supply_units"], "count"),
            ],
            "sampleSize": {"sales": d["sales"]["count"], "rentals": d["rentals"]["count"]},
        })

    verdict = []
    if len(details) == 2:
        a, b = details
        def _winner(key_path, higher_is_better=True):
            av = a
            bv = b
            for k in key_path:
                av = av[k] if av else None
                bv = bv[k] if bv else None
            if av is None or bv is None:
                return None, "Insufficient data"
            if av == bv:
                return None, "Tied"
            winner = a if (av > bv) == higher_is_better else b
            return winner["community_name"], f"{av} vs {bv}"

        y_winner, y_detail = _winner(["estimated_gross_yield_pct"], True)
        p_winner, p_detail = _winner(["sales", "median_price"], False)  # lower entry price wins
        liq_winner, liq_detail = _winner(["sales", "count"], True)
        supply_a = a["upcoming_supply_units"] or 0
        supply_b = b["upcoming_supply_units"] or 0
        supply_winner = a["community_name"] if supply_a < supply_b else (b["community_name"] if supply_b < supply_a else None)

        verdict = [
            {"dimension": "Rental Yield", "winner": y_winner, "detail": y_detail},
            {"dimension": "Lower Entry Price", "winner": p_winner, "detail": p_detail},
            {"dimension": "Liquidity (sales volume)", "winner": liq_winner, "detail": liq_detail},
            {"dimension": "Lower Supply Risk", "winner": supply_winner, "detail": f"{supply_a} vs {supply_b} incoming units"},
        ]

    facts = []
    if len(details) == 2:
        a, b = details
        facts.append(f"{a['community_name']} recorded {a['sales']['count']} sales vs {b['community_name']}'s {b['sales']['count']} this {window.label}.")
        if a["estimated_gross_yield_pct"] and b["estimated_gross_yield_pct"]:
            facts.append(f"{a['community_name']} yields an estimated {a['estimated_gross_yield_pct']}% vs {b['estimated_gross_yield_pct']}% in {b['community_name']}.")
        if a["sales"]["median_price"] and b["sales"]["median_price"]:
            diff = pct_change(a["sales"]["median_price"], b["sales"]["median_price"])
            if diff is not None:
                facts.append(f"{a['community_name']}'s median sale price is {abs(diff):.0f}% {'higher' if diff > 0 else 'lower'} than {b['community_name']}'s.")

    return {
        "question": f"Where would an investor get the better risk-adjusted opportunity — {entities[0]['label'] if entities else '?'} or {entities[1]['label'] if len(entities) > 1 else '?'}?",
        "period": window.label,
        "entities": entities,
        "verdict": verdict,
        "reelReadyFacts": facts,
        "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Compares like-for-like: registered DLD transactions and rent contracts only, no asking-price data.",
        "sources": ["DLD-T", "DLD-R"],
    }


# ---------------------------------------------------------------------------
# 3. Yield ranking — category "Rental & Yield Reels" (#36-55).
# ---------------------------------------------------------------------------
def yield_ranking(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    bedroom = params.get("bedroom")
    budget_max = params.get("budgetMax")
    limit = int(params.get("limit") or 15)

    bedroom_clause_s = " AND fs.canonical_bedroom = ?" if bedroom else ""
    bedroom_clause_r = " AND fr.canonical_bedroom = ?" if bedroom else ""
    s_params = [window.current_start, window.current_end] + ([bedroom] if bedroom else [])
    r_params = [window.current_start, window.current_end] + ([bedroom] if bedroom else [])

    sales_rows = con.execute(
        f"""
        SELECT da.community_key, da.community_name, count(*) c, median(fs.trans_value_aed) mp
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'{bedroom_clause_s}
        GROUP BY 1, 2
        """,
        s_params,
    ).fetchall()
    rental_rows = {
        r[0]: r[1:] for r in con.execute(
            f"""
            SELECT da.community_key, count(*) c, median(fr.annual_amount_aed) mr
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ?{bedroom_clause_r}
            GROUP BY 1
            """,
            r_params,
        ).fetchall()
    }

    ranked = []
    for key, name, sales_count, median_price in sales_rows:
        r = rental_rows.get(key)
        if not r or sales_count < MIN_SAMPLE or r[0] < MIN_SAMPLE:
            continue
        rental_count, median_rent = r
        if budget_max and median_price and median_price > float(budget_max):
            continue
        y = estimated_gross_yield(median_rent, median_price)
        if y is None:
            continue
        ranked.append({
            "id": key, "label": name.upper(), "subtitle": f"{sales_count} sales · {rental_count} rentals",
            "metrics": [
                _metric("Est. Gross Yield", y, "pct", _yield_tone(y)),
                _metric("Median Price", median_price, "aed"),
                _metric("Median Annual Rent", median_rent, "aed"),
                _metric("Sales", sales_count, "count"),
                _metric("Rentals", rental_count, "count"),
            ],
            "sampleSize": {"sales": sales_count, "rentals": rental_count},
            "_yield": y,
        })
    ranked.sort(key=lambda x: x["_yield"], reverse=True)
    for e in ranked:
        del e["_yield"]
    ranked = ranked[:limit]

    facts = []
    if ranked:
        top = ranked[0]
        y_metric = next(m for m in top["metrics"] if m["label"] == "Est. Gross Yield")
        facts.append(f"{top['label']} currently posts Dubai's highest estimated gross yield among communities with sufficient sample size, at {y_metric['value']}%.")
    if len(ranked) >= 2:
        facts.append(f"The top {min(5, len(ranked))} yielding communities range from {ranked[0]['metrics'][0]['value']}% down to {ranked[min(4,len(ranked)-1)]['metrics'][0]['value']}%.")

    bedroom_label = f" ({bedroom})" if bedroom else ""
    budget_label = f" under AED {int(float(budget_max)):,}" if budget_max else ""
    return {
        "question": f"Which Dubai communities have the highest rental yield{bedroom_label}{budget_label} right now?",
        "period": window.label,
        "entities": ranked,
        "verdict": None,
        "reelReadyFacts": facts,
        "whatIsInteresting": facts[0] if facts else None,
        "caveat": f"Yield = median annual rent / median sale price, both registered DLD figures. Minimum sample size: {MIN_SAMPLE} sales and {MIN_SAMPLE} rentals per community.",
        "sources": ["DLD-T", "DLD-R"],
    }


# ---------------------------------------------------------------------------
# 4. PSF ranking / distribution — category "Price per Square Foot" (#110-123).
# ---------------------------------------------------------------------------
def psf_ranking(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    budget_max = params.get("psfMax")
    limit = int(params.get("limit") or 15)
    community_key = params.get("community")

    if community_key:
        row = con.execute(
            """
            SELECT quantile_cont(fs.price_per_sqft_aed, 0.25), median(fs.price_per_sqft_aed),
                   avg(fs.price_per_sqft_aed), quantile_cont(fs.price_per_sqft_aed, 0.75), count(*)
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND fs.price_per_sqft_aed IS NOT NULL
            """,
            [community_key, window.current_start, window.current_end],
        ).fetchone()
        p25, med, avg, p75, n = row
        name_row = con.execute("SELECT community_name FROM dim_area WHERE community_key = ? LIMIT 1", [community_key]).fetchone()
        name = name_row[0] if name_row else community_key
        entities = [{
            "id": community_key, "label": name.upper(), "subtitle": f"PSF distribution · {n} sales",
            "metrics": [
                _metric("Median PSF", med, "psf"),
                _metric("Average PSF", avg, "psf"),
                _metric("25th Percentile", p25, "psf"),
                _metric("75th Percentile", p75, "psf"),
            ],
            "sampleSize": {"sales": n, "rentals": 0},
        }]
        facts = []
        if med and avg and abs(med - avg) / med > 0.05:
            facts.append(f"Average PSF (AED {avg:.0f}) diverges from median PSF (AED {med:.0f}) — outlier transactions are skewing the average.")
        return {
            "question": f"What does the PSF distribution actually look like in {name}?",
            "period": window.label, "entities": entities, "verdict": None,
            "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
            "caveat": "Median is the more reliable headline figure for pricing content — average is shown for comparison, not as the hero number.",
            "sources": ["DLD-T"],
        }

    rows = con.execute(
        """
        SELECT da.community_key, da.community_name, count(*) c, median(fs.price_per_sqft_aed) med
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND fs.price_per_sqft_aed IS NOT NULL
        GROUP BY 1, 2 HAVING count(*) >= ?
        ORDER BY med ASC
        """,
        [window.current_start, window.current_end, MIN_SAMPLE],
    ).fetchall()
    if budget_max:
        rows = [r for r in rows if r[3] and r[3] <= float(budget_max)]
    ranked = [{
        "id": key, "label": name.upper(), "subtitle": f"{c} sales",
        "metrics": [_metric("Median PSF", med, "psf"), _metric("Sales", c, "count")],
        "sampleSize": {"sales": c, "rentals": 0},
    } for key, name, c, med in rows[:limit]]

    facts = []
    if ranked:
        facts.append(f"{ranked[0]['label']} has Dubai's lowest median transaction PSF among communities with a reliable sample, at {ranked[0]['metrics'][0]['value']:.0f} AED/sqft." if ranked[0]["metrics"][0]["value"] else "")
    facts = [f for f in facts if f]
    return {
        "question": "Which Dubai communities trade at the lowest price per square foot?" if not budget_max else f"Where is PSF under {budget_max} cheap in Dubai?",
        "period": window.label, "entities": ranked, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Median transacted PSF, not asking-price PSF.",
        "sources": ["DLD-T"],
    }


# ---------------------------------------------------------------------------
# 5. Liquidity ranking — category "Liquidity / Exit Reels" (#124-135).
# ---------------------------------------------------------------------------
def liquidity_ranking(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    limit = int(params.get("limit") or 15)
    days_span = (window.current_end - window.current_start).days + 1
    months_span = max(days_span / 30.44, 0.1)

    rows = con.execute(
        """
        SELECT da.community_key, da.community_name, count(*) c,
               count(DISTINCT date_trunc('month', fs.instance_date)) active_months
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        GROUP BY 1, 2 HAVING count(*) >= ?
        """,
        [window.current_start, window.current_end, MIN_SAMPLE],
    ).fetchall()
    total_months = max(1, round(months_span))
    ranked = []
    for key, name, c, active_months in rows:
        consistency = min(active_months / total_months, 1.0)
        score = liquidity_score(c, months_span, consistency)
        ranked.append({
            "id": key, "label": name.upper(), "subtitle": f"{c} sales over {window.label}",
            "metrics": [
                _metric("Liquidity Score", score["score"], "count"),
                _metric("Transactions/Month", score["monthly_rate"], "count"),
                _metric("Total Transactions", c, "count"),
                _metric("Active Months", active_months, "count"),
            ],
            "sampleSize": {"sales": c, "rentals": 0},
            "_score": score["score"],
        })
    ranked.sort(key=lambda x: x["_score"], reverse=True)
    for e in ranked:
        del e["_score"]
    ranked = ranked[:limit]

    price_bands = con.execute(
        """
        SELECT
          CASE
            WHEN trans_value_aed < 750000 THEN '< 750K'
            WHEN trans_value_aed < 1000000 THEN '750K-1M'
            WHEN trans_value_aed < 1500000 THEN '1M-1.5M'
            WHEN trans_value_aed < 2000000 THEN '1.5M-2M'
            WHEN trans_value_aed < 3000000 THEN '2M-3M'
            ELSE '3M+'
          END band, count(*) c
        FROM fact_sales WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales' AND trans_value_aed IS NOT NULL
        GROUP BY 1
        """,
        [window.current_start, window.current_end],
    ).fetchall()
    band_order = ["< 750K", "750K-1M", "1M-1.5M", "1.5M-2M", "2M-3M", "3M+"]
    band_map = dict(price_bands)
    bands_sorted = [{"label": b, "value": band_map.get(b, 0)} for b in band_order]

    facts = []
    if ranked:
        facts.append(f"{ranked[0]['label']} is the easiest Dubai community to transact in right now, based on transaction frequency and consistency.")
    if bands_sorted:
        deepest = max(bands_sorted, key=lambda b: b["value"])
        facts.append(f"The {deepest['label']} price band has the deepest buyer pool ({deepest['value']} transactions this {window.label}).")

    return {
        "question": "Which Dubai communities offer the easiest exit / resale liquidity?",
        "period": window.label, "entities": ranked, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Liquidity score formula: 100 * (0.7 * min(monthly_rate/50, 1) + 0.3 * consistency) — see liquidity_score in analytics/core.py. A proxy for resale ease, not a guarantee.",
        "sources": ["DLD-T"],
        "priceBandDepth": bands_sorted,
    }


# ---------------------------------------------------------------------------
# 6. Developer ranking — category "Developer Reels" (#96-109).
# ---------------------------------------------------------------------------
def developer_ranking(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    limit = int(params.get("limit") or 15)

    rows = con.execute(
        """
        SELECT dmp.developer_name, count(*) c, sum(fs.trans_value_aed) v, median(fs.price_per_sqft_aed) psf
        FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
        JOIN dim_master_project dmp ON dp.master_project_id = dmp.master_project_id
        WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND dmp.developer_name IS NOT NULL
        GROUP BY 1 HAVING count(*) >= ?
        ORDER BY c DESC LIMIT ?
        """,
        [window.current_start, window.current_end, MIN_SAMPLE, limit],
    ).fetchall()

    pipeline = dict(con.execute(
        """
        SELECT dev.name, sum(us.total_units)
        FROM scraped.unit_supply us
        JOIN scraped.developments d ON us.development_id = d.id
        JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE d.normalized_status IN ('under_construction', 'planned', 'announced')
        GROUP BY 1
        """
    ).fetchall())

    ranked = [{
        "id": name, "label": name.upper(), "subtitle": f"{c} sales this {window.label}",
        "metrics": [
            _metric("Sales Count", c, "count"),
            _metric("Sales Value", v, "aed"),
            _metric("Median PSF", psf, "psf"),
            _metric("Pipeline (upcoming units)", pipeline.get(name), "count"),
        ],
        "sampleSize": {"sales": c, "rentals": 0},
    } for name, c, v, psf in rows]

    facts = []
    if ranked:
        facts.append(f"{ranked[0]['label']} was Dubai's best-selling developer this {window.label}, with {ranked[0]['metrics'][0]['value']} recorded sales.")
    biggest_pipeline = max(pipeline.items(), key=lambda x: x[1], default=None)
    if biggest_pipeline:
        facts.append(f"{biggest_pipeline[0]} has the largest active pipeline at {int(biggest_pipeline[1]):,} upcoming units.")

    return {
        "question": "Which developers are selling the most in Dubai right now?",
        "period": window.label, "entities": ranked, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Developer attribution comes from entity-resolved project matching between DLD transaction records and the scraped project catalog — projects that couldn't be matched to a developer are excluded.",
        "sources": ["DLD-T", "DLD-P"],
    }


# ---------------------------------------------------------------------------
# 7. Budget explorer — category "Budget-Based Reels" (#136-150) and the
#    budget-flavored half of "What Would I Buy?" (#178-192).
# ---------------------------------------------------------------------------
def budget_explorer(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    budget = float(params.get("budget") or 1_000_000)
    tolerance = float(params.get("tolerancePct") or 15) / 100
    bedroom = params.get("bedroom")
    limit = int(params.get("limit") or 15)

    lo, hi = budget * (1 - tolerance), budget * (1 + tolerance)
    bedroom_clause = " AND fs.canonical_bedroom = ?" if bedroom else ""
    q_params = [lo, hi, window.current_start, window.current_end] + ([bedroom] if bedroom else [])

    rows = con.execute(
        f"""
        SELECT da.community_name, da.community_key, fs.canonical_bedroom, fs.canonical_property_type,
               count(*) c, median(fs.trans_value_aed) med, median(fs.price_per_sqft_aed) psf
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE fs.trans_value_aed BETWEEN ? AND ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'{bedroom_clause}
        GROUP BY 1, 2, 3, 4 HAVING count(*) >= 3
        ORDER BY c DESC LIMIT ?
        """,
        q_params + [limit],
    ).fetchall()

    rental_by_community_bedroom = {
        (r[0], r[1]): r[2] for r in con.execute(
            """
            SELECT da.community_key, fr.canonical_bedroom, median(fr.annual_amount_aed)
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? GROUP BY 1, 2
            """,
            [window.current_start, window.current_end],
        ).fetchall()
    }

    ranked = []
    for name, key, bedroom_val, ptype, c, med, psf in rows:
        rent = rental_by_community_bedroom.get((key, bedroom_val))
        y = estimated_gross_yield(rent, med)
        ranked.append({
            "id": f"{key}:{bedroom_val}:{ptype}", "label": f"{name.upper()} · {bedroom_val}",
            "subtitle": f"{ptype or 'Property'} · {c} comparable sales",
            "metrics": [
                _metric("Median Price", med, "aed"),
                _metric("Median PSF", psf, "psf"),
                _metric("Est. Yield", y, "pct", _yield_tone(y)) if y is not None else _metric("Est. Yield", None, "pct"),
                _metric("Comparable Sales", c, "count"),
            ],
            "sampleSize": {"sales": c, "rentals": 0},
        })

    facts = []
    if ranked:
        facts.append(f"AED {budget:,.0f} buys a {ranked[0]['label'].split(' · ')[1]} in {ranked[0]['label'].split(' · ')[0].title()}, based on {ranked[0]['sampleSize']['sales']} comparable recent sales.")

    return {
        "question": f"What does AED {budget:,.0f} actually buy in Dubai right now?",
        "period": window.label, "entities": ranked, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": f"Shows real registered transactions within ±{int(tolerance*100)}% of the target budget — not asking prices or live listings.",
        "sources": ["DLD-T", "DLD-R"],
    }


# ---------------------------------------------------------------------------
# 8. Supply analysis — category "Supply / Oversupply" (#81-95).
# ---------------------------------------------------------------------------
def supply_analysis(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    community_key = params.get("community")
    if not community_key:
        community_key = _top_communities(con, window, 1)
        community_key = community_key[0] if community_key else None

    if not community_key:
        return {
            "question": "Which Dubai communities carry the biggest supply risk?",
            "period": window.label, "entities": [], "verdict": None,
            "reelReadyFacts": [], "whatIsInteresting": None,
            "caveat": "No community specified and no data available.", "sources": ["DLD-P"],
        }

    name_row = con.execute("SELECT community_name, scraped_area_id FROM dim_area WHERE community_key = ? LIMIT 1", [community_key]).fetchone()
    name, scraped_area_id = name_row if name_row else (community_key, None)

    incoming = 0
    by_status: list[tuple] = []
    if scraped_area_id is not None:
        by_status = con.execute(
            """
            SELECT d.normalized_status, sum(us.total_units)
            FROM scraped.unit_supply us JOIN scraped.developments d ON us.development_id = d.id
            WHERE d.area_id = ? GROUP BY 1
            """,
            [scraped_area_id],
        ).fetchall()
        incoming = sum(
            u for status, u in by_status if status in ("under_construction", "planned", "announced") and u
        )

    rentals_count = con.execute(
        "SELECT count(*) FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id WHERE da.community_key = ? AND fr.registration_date BETWEEN ? AND ?",
        [community_key, window.current_start, window.current_end],
    ).fetchone()[0]
    days = (window.current_end - window.current_start).days + 1
    annualized_demand = round(rentals_count * 365 / days, 0) if days > 0 else None
    risk = oversupply_risk(incoming if incoming else None, annualized_demand)

    sales_count = con.execute(
        "SELECT count(*) FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'",
        [community_key, window.current_start, window.current_end],
    ).fetchone()[0]

    entities = [{
        "id": community_key, "label": name.upper(), "subtitle": f"Supply vs demand — {window.label}",
        "metrics": [
            _metric("Incoming Units (pipeline)", incoming or None, "count"),
            _metric("Annualized Rental Demand", annualized_demand, "count"),
            _metric("Supply Risk", risk["risk"], "text", "bad" if risk["risk"] in ("high", "very_high") else "neutral"),
            _metric("Sales This Period", sales_count, "count"),
            _metric("Rentals This Period", rentals_count, "count"),
        ],
        "sampleSize": {"sales": sales_count, "rentals": rentals_count},
        "breakdown": {"byStatus": [{"label": (s or "unknown").replace("_", " ").title(), "value": u} for s, u in by_status]},
    }]

    facts = []
    if incoming:
        facts.append(f"{name} has approximately {int(incoming):,} units in the pipeline (under construction, planned, or announced).")
    if annualized_demand:
        facts.append(f"Annualized rental demand in {name} is currently around {int(annualized_demand):,} contracts.")
    if risk["ratio"] is not None:
        facts.append(f"Pipeline-to-demand ratio: {risk['ratio']}x ({risk['risk'].replace('_', ' ')} supply risk).")

    return {
        "question": f"Is {name} facing a real supply risk?",
        "period": window.label, "entities": entities, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[-1] if facts else None,
        "caveat": risk["note"] + " Pipeline figures are registered/announced units from the scraped project catalog, not a guarantee of delivery timing.",
        "sources": ["DLD-P", "DLD-R", "DLD-T"],
    }


# ---------------------------------------------------------------------------
# 9. Project scorecard — categories "Off-Plan Project Analysis" (#56-80) and
#    "Is This Project Overpriced?" (#166-177).
# ---------------------------------------------------------------------------
def project_scorecard(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    from apps.api.routers.projects import master_project_detail

    slug = params.get("project")
    if not slug:
        row = con.execute(
            "SELECT slug FROM dim_master_project ORDER BY building_count DESC LIMIT 1"
        ).fetchone()
        slug = row[0] if row else None
    if not slug:
        return {
            "question": "Is this project a good investment?",
            "period": period, "entities": [], "verdict": None,
            "reelReadyFacts": [], "whatIsInteresting": None,
            "caveat": "No project available.", "sources": ["DLD-T", "DLD-P"],
        }

    detail = master_project_detail(slug, period, con=con)
    window_label = detail["period"]
    kpis = detail["kpis"]

    community_psf = None
    if detail.get("area_name"):
        row = con.execute(
            "SELECT median(fs.price_per_sqft_aed) FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id WHERE da.community_name = ? AND fs.group_en = 'Sales'",
            [detail["area_name"]],
        ).fetchone()
        community_psf = row[0] if row else None

    project_psf = kpis["sales"]["median_psf"]
    premium_pct = pct_change(project_psf, community_psf) if project_psf and community_psf else None

    entities = [{
        "id": slug, "label": detail["name"].upper(),
        "subtitle": f"{detail.get('developer_name') or 'Unknown developer'} · {detail['area_name'] or 'Unknown area'}",
        "metrics": [
            _metric("Project Median PSF", project_psf, "psf"),
            _metric(f"{detail['area_name'] or 'Community'} Median PSF", community_psf, "psf"),
            _metric("PSF Premium vs Community", premium_pct, "pct_signed", "bad" if (premium_pct or 0) > 15 else "neutral"),
            _metric("Est. Gross Yield", kpis["market"]["estimated_gross_yield_pct"], "pct", _yield_tone(kpis["market"]["estimated_gross_yield_pct"])),
            _metric("Sales This Period", kpis["sales"]["count"], "count"),
            _metric("Rental Contracts", kpis["rentals"]["count"], "count"),
            _metric("Liquidity Score", kpis["market"]["liquidity"]["score"] if kpis["market"].get("liquidity") else None, "count"),
            _metric("Buildings", detail["building_count"], "count"),
        ],
        "sampleSize": {"sales": kpis["sales"]["count"], "rentals": kpis["rentals"]["count"]},
    }]

    facts = []
    if premium_pct is not None:
        direction = "above" if premium_pct > 0 else "below"
        facts.append(f"{detail['name']} trades {abs(premium_pct):.0f}% {direction} the {detail['area_name']} community median PSF.")
    if kpis["market"]["estimated_gross_yield_pct"]:
        facts.append(f"Estimated gross yield: {kpis['market']['estimated_gross_yield_pct']}%, based on registered rents in the same buildings.")
    if kpis["sales"]["count"]:
        facts.append(f"{kpis['sales']['count']} units traded in {detail['name']} this {window_label}.")

    return {
        "question": f"Is {detail['name']} actually a good investment at today's PSF?",
        "period": window_label, "entities": entities, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Launch price, payment plan, and official handover date are developer-published information this database does not carry — this scorecard covers the transaction/rental/liquidity side only.",
        "sources": ["DLD-T", "DLD-P", "DEV"],
        "availableProjects": [r[0] for r in con.execute("SELECT slug FROM dim_master_project ORDER BY building_count DESC LIMIT 50").fetchall()],
    }


# ---------------------------------------------------------------------------
# 10. Building-level insight — category "The Data Nobody Shows You" (#208-227).
# ---------------------------------------------------------------------------
def building_insight(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    community_key = params.get("community")
    if not community_key:
        top = _top_communities(con, window, 1)
        community_key = top[0] if top else None
    kind = params.get("kind", "rentals")
    limit = int(params.get("limit") or 10)

    if not community_key:
        return {
            "question": "Which building has the strongest activity?",
            "period": window.label, "entities": [], "verdict": None,
            "reelReadyFacts": [], "whatIsInteresting": None,
            "caveat": "No data available.", "sources": ["OWN"],
        }

    name_row = con.execute("SELECT community_name FROM dim_area WHERE community_key = ? LIMIT 1", [community_key]).fetchone()
    name = name_row[0] if name_row else community_key

    if kind == "sales":
        rows = con.execute(
            """
            SELECT COALESCE(dp.building_label, dp.dld_project_name), count(*), median(fs.trans_value_aed), median(fs.price_per_sqft_aed)
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id JOIN dim_project dp ON fs.project_id = dp.project_id
            WHERE da.community_key = ? AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' AND dp.dld_project_name IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC LIMIT ?
            """,
            [community_key, window.current_start, window.current_end, limit],
        ).fetchall()
        metric_label = "Sales"
    else:
        rows = con.execute(
            """
            SELECT COALESCE(dp.building_label, dp.dld_project_name), count(*), median(fr.annual_amount_aed), NULL
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id JOIN dim_project dp ON fr.project_id = dp.project_id
            WHERE da.community_key = ? AND fr.registration_date BETWEEN ? AND ? AND dp.dld_project_name IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC LIMIT ?
            """,
            [community_key, window.current_start, window.current_end, limit],
        ).fetchall()
        metric_label = "Rental Contracts"

    ranked = [{
        "id": f"{community_key}:{bname}", "label": (bname or "Unknown building").upper(),
        "subtitle": f"{name} · {c} {metric_label.lower()}",
        "metrics": [
            _metric(metric_label, c, "count"),
            _metric("Median " + ("Price" if kind == "sales" else "Annual Rent"), med, "aed"),
        ] + ([_metric("Median PSF", psf, "psf")] if kind == "sales" and psf else []),
        "sampleSize": {"sales": c if kind == "sales" else 0, "rentals": c if kind == "rentals" else 0},
    } for bname, c, med, psf in rows]

    facts = []
    if ranked:
        facts.append(f"{ranked[0]['label']} is the most {'traded' if kind == 'sales' else 'rented'} building in {name}, with {ranked[0]['metrics'][0]['value']} {metric_label.lower()} this {window.label}.")

    return {
        "question": f"Which building in {name} has the strongest {'transaction' if kind == 'sales' else 'rental demand'} activity?",
        "period": window.label, "entities": ranked, "verdict": None,
        "reelReadyFacts": facts, "whatIsInteresting": facts[0] if facts else None,
        "caveat": "Building identity comes from DLD project-name parsing (e.g. distinguishing tower/building suffixes within one master project) — not a formal building registry.",
        "sources": ["OWN", "DLD-T" if kind == "sales" else "DLD-R"],
    }


# ---------------------------------------------------------------------------
# 11. Myth test — category "Myth-Busting Reels" (#193-207). Thin wrapper:
#     picks the most relevant existing resolver and adds claim/verdict framing.
# ---------------------------------------------------------------------------
def myth_test(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    underlying = params.get("underlying", "market_snapshot")
    resolver = RESOLVERS.get(underlying, market_snapshot)
    result = resolver(con, period, params)
    result["claim"] = params.get("claim", "")
    result["question"] = params.get("claim") or result["question"]
    return result


# ---------------------------------------------------------------------------
# 12. Macro — category "Population / Demand / Macro Reels" (#151-165).
#     Genuinely external for population/infrastructure claims; where the
#     transaction data itself can proxy demand, it's surfaced honestly as
#     a partial signal rather than invented population figures.
# ---------------------------------------------------------------------------
def macro(con: duckdb.DuckDBPyConnection, period: str, params: dict) -> dict:
    window = resolve_period(con, period)
    sales_count = con.execute(
        "SELECT count(*) FROM fact_sales WHERE instance_date BETWEEN ? AND ? AND group_en = 'Sales'",
        [window.current_start, window.current_end],
    ).fetchone()[0]
    return {
        "question": "What does the data say about Dubai's population/demand growth vs housing supply?",
        "period": window.label,
        "entities": [{
            "id": "dubai", "label": "DUBAI", "subtitle": "Transaction volume as a demand proxy only",
            "metrics": [_metric("Transactions This Period", sales_count, "count")],
            "sampleSize": {"sales": sales_count, "rentals": 0},
        }],
        "verdict": None,
        "reelReadyFacts": [],
        "whatIsInteresting": None,
        "caveat": "Population statistics (DDSE), Dubai 2040 master-plan data, and RTA infrastructure announcements are not present in this database — this reel needs those official sources before it can run. Transaction volume is shown only as a rough demand proxy.",
        "sources": ["DDSE", "2040/RTA"],
    }


RESOLVERS = {
    "market_snapshot": market_snapshot,
    "community_comparison": community_comparison,
    "yield_ranking": yield_ranking,
    "psf_ranking": psf_ranking,
    "liquidity_ranking": liquidity_ranking,
    "developer_ranking": developer_ranking,
    "budget_explorer": budget_explorer,
    "supply_analysis": supply_analysis,
    "project_scorecard": project_scorecard,
    "building_insight": building_insight,
    "myth_test": myth_test,
    "macro": macro,
}
