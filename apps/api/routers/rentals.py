from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import market_share, resolve_period
from apps.api.db import db

router = APIRouter()

_BREAKDOWN_DIMENSIONS = {
    "community": "da.community_name",
    "property_type": "fr.canonical_property_type",
    "bedroom": "fr.canonical_bedroom",
    "contract_type": "CASE WHEN fr.is_renewal THEN 'Renewal' ELSE 'New' END",
    "project": "dp.dld_project_name",
}


@router.get("/breakdown")
def rentals_breakdown(by: str = "community", period: str = "90d", community_key: str | None = None, limit: int = 20, con=Depends(db)):
    window = resolve_period(con, period)
    dim = _BREAKDOWN_DIMENSIONS.get(by, _BREAKDOWN_DIMENSIONS["community"])
    where = "fr.registration_date BETWEEN ? AND ?"
    params: list = [window.current_start, window.current_end]
    if community_key:
        where += " AND da.community_key = ?"
        params.append(community_key)

    rows = con.execute(
        f"""
        SELECT {dim} AS label, count(*) c, median(fr.annual_amount_aed) mr, median(fr.rent_per_sqft_aed) rpsf
        FROM fact_rentals fr
        JOIN dim_area da ON fr.area_id = da.area_id
        LEFT JOIN dim_project dp ON fr.project_id = dp.project_id
        WHERE {where} AND {dim} IS NOT NULL
        GROUP BY 1 ORDER BY c DESC LIMIT ?
        """,
        params + [limit],
    ).fetchall()

    total = sum(r[1] for r in rows)
    return {
        "period": window.label, "by": by,
        "items": [
            {"label": r[0], "count": r[1], "median_rent": r[2], "median_rent_psf": r[3], "share_pct": market_share(r[1], total)}
            for r in rows
        ],
    }


@router.get("/trend")
def rentals_trend(period: str = "6m", granularity: str = "week", community_key: str | None = None, con=Depends(db)):
    window = resolve_period(con, period)
    bucket = {"day": "day", "week": "week", "month": "month"}.get(granularity, "week")
    where = "registration_date BETWEEN ? AND ?"
    params: list = [window.current_start, window.current_end]
    if community_key:
        where += " AND area_id IN (SELECT area_id FROM dim_area WHERE community_key = ?)"
        params.append(community_key)

    rows = con.execute(
        f"""
        SELECT date_trunc('{bucket}', registration_date) AS bucket, count(*) c, median(annual_amount_aed) mr,
               sum(is_renewal) renewals, sum(NOT is_renewal) new_contracts
        FROM fact_rentals WHERE {where}
        GROUP BY 1 ORDER BY 1
        """,
        params,
    ).fetchall()
    return {
        "period": window.label, "granularity": granularity,
        "points": [{"date": r[0].isoformat(), "count": r[1], "median_rent": r[2], "renewals": r[3], "new_contracts": r[4]} for r in rows],
    }


@router.get("/demand-matrix")
def demand_matrix(period: str = "90d", metric: str = "absolute", top_n_communities: int = 15, con=Depends(db)):
    """Community x bedroom matrix of rental activity. `metric`:
    - absolute: raw contract counts
    - share: % of that community's rental activity (rows sum to 100)
    """
    window = resolve_period(con, period)
    top_communities = con.execute(
        """
        SELECT da.community_key, da.community_name, count(*) c
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE fr.registration_date BETWEEN ? AND ?
        GROUP BY 1, 2 ORDER BY c DESC LIMIT ?
        """,
        [window.current_start, window.current_end, top_n_communities],
    ).fetchall()
    community_keys = [r[0] for r in top_communities]
    if not community_keys:
        return {"period": window.label, "metric": metric, "communities": [], "bedrooms": [], "matrix": []}

    placeholders = ", ".join(["?"] * len(community_keys))
    rows = con.execute(
        f"""
        SELECT da.community_key, fr.canonical_bedroom, count(*) c
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE fr.registration_date BETWEEN ? AND ? AND da.community_key IN ({placeholders})
        GROUP BY 1, 2
        """,
        [window.current_start, window.current_end] + community_keys,
    ).fetchall()

    bedrooms = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR+", "Unknown", "Other"]
    grid: dict[str, dict[str, int]] = {ck: {b: 0 for b in bedrooms} for ck in community_keys}
    for ck, bedroom, c in rows:
        if ck in grid and bedroom in grid[ck]:
            grid[ck][bedroom] = c

    matrix = []
    for ck, name, total in top_communities:
        row_counts = grid[ck]
        if metric == "share":
            row_total = sum(row_counts.values()) or 1
            values = {b: market_share(v, row_total) for b, v in row_counts.items()}
        else:
            values = row_counts
        matrix.append({"community_key": ck, "community_name": name, "total": total, "values": values})

    return {"period": window.label, "metric": metric, "bedrooms": bedrooms, "matrix": matrix}
