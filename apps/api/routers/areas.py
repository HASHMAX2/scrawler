from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.analytics.core import estimated_gross_yield, resolve_period
from apps.api.db import db
from apps.api.routers.communities import _area_profile, _livability_panel

router = APIRouter()

# Scraped areas form a tree via the free-text areas.parent_area_name field
# (self-referencing by name, not id — that's how Propsearch's own page
# breadcrumbs work). Depth is capped defensively against a bad/cyclic
# parent_area_name value; real data never goes deeper than ~4 levels
# (Dubai -> Area -> Sub-community -> POI).
MAX_DEPTH = 8


def _subtree_ids(con, root_id: int) -> list[int]:
    rows = con.execute(
        f"""
        WITH RECURSIVE area_tree(id, name, depth) AS (
            SELECT id, name, 0 FROM scraped.areas WHERE id = ?
            UNION ALL
            SELECT a.id, a.name, t.depth + 1
            FROM scraped.areas a JOIN area_tree t ON a.parent_area_name = t.name
            WHERE a.area_type = 'community' AND t.depth < {MAX_DEPTH}
        )
        SELECT id FROM area_tree
        """,
        [root_id],
    ).fetchall()
    return [r[0] for r in rows]


def _rollup_stats(con, area_ids: list[int], window) -> dict:
    if not area_ids:
        return {
            "sales_count": 0, "sales_value": None, "median_price": None,
            "rental_count": 0, "median_rent": None, "estimated_gross_yield_pct": None,
        }
    placeholders = ", ".join(["?"] * len(area_ids))
    sales = con.execute(
        f"""
        SELECT count(*), sum(fs.trans_value_aed), median(fs.trans_value_aed)
        FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
        WHERE da.scraped_area_id IN ({placeholders}) AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        """,
        area_ids + [window.current_start, window.current_end],
    ).fetchone()
    rentals = con.execute(
        f"""
        SELECT count(*), median(fr.annual_amount_aed)
        FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
        WHERE da.scraped_area_id IN ({placeholders}) AND fr.registration_date BETWEEN ? AND ?
        """,
        area_ids + [window.current_start, window.current_end],
    ).fetchone()
    return {
        "sales_count": sales[0], "sales_value": sales[1], "median_price": sales[2],
        "rental_count": rentals[0], "median_rent": rentals[1],
        "estimated_gross_yield_pct": estimated_gross_yield(rentals[1], sales[2]),
    }


def _child_count(con, parent_name: str) -> int:
    return con.execute(
        "SELECT count(*) FROM scraped.areas WHERE parent_area_name = ? AND area_type = 'community'",
        [parent_name],
    ).fetchone()[0]


@router.get("")
def list_top_level_areas(period: str = "90d", con=Depends(db)):
    """The 92 top-level Dubai areas (Propsearch's own area-guide roots), each
    with rolled-up DLD stats summed across its entire sub-community subtree —
    DLD reports at the broad community grain, not per sub-district, so a
    single sub-area's own numbers are usually near-zero; the subtree rollup
    is where the real signal lives.
    """
    window = resolve_period(con, period)
    roots = con.execute(
        """
        SELECT id, name, hero_image_url, also_known_as FROM scraped.areas
        WHERE parent_area_name = 'Dubai' AND area_type = 'community'
        ORDER BY name
        """
    ).fetchall()
    items = []
    for area_id, name, hero, aka in roots:
        subtree = _subtree_ids(con, area_id)
        stats = _rollup_stats(con, subtree, window)
        items.append({
            "area_id": area_id, "name": name, "hero_image_url": hero, "also_known_as": aka,
            "child_count": _child_count(con, name), "descendant_count": len(subtree) - 1,
            **stats,
        })
    items.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)
    return {"period": window.label, "items": items}


@router.get("/{area_id}")
def area_detail(area_id: int, period: str = "90d", con=Depends(db)):
    window = resolve_period(con, period)
    row = con.execute("SELECT id, name, parent_area_name, area_type FROM scraped.areas WHERE id = ?", [area_id]).fetchone()
    if not row:
        raise HTTPException(404, "Unknown area_id")
    _, name, parent_name, area_type = row

    breadcrumb = []
    cur_name, seen = parent_name, set()
    while cur_name and cur_name != "Dubai" and cur_name not in seen:
        seen.add(cur_name)
        prow = con.execute("SELECT id, name, parent_area_name FROM scraped.areas WHERE name = ? LIMIT 1", [cur_name]).fetchone()
        if not prow:
            break
        breadcrumb.append({"area_id": prow[0], "name": prow[1]})
        cur_name = prow[2]
    breadcrumb.reverse()

    own_stats = _rollup_stats(con, [area_id], window)
    subtree = _subtree_ids(con, area_id)
    subtree_stats = _rollup_stats(con, subtree, window) if len(subtree) > 1 else own_stats

    children_rows = con.execute(
        """
        SELECT id, name, hero_image_url FROM scraped.areas
        WHERE parent_area_name = ? AND area_type = 'community' ORDER BY name
        """,
        [name],
    ).fetchall()
    children = []
    for cid, cname, chero in children_rows:
        children.append({
            "area_id": cid, "name": cname, "hero_image_url": chero,
            "community_key": f"s{cid}", "child_count": _child_count(con, cname),
            **_rollup_stats(con, [cid], window),
        })
    children.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)

    match_confidence = con.execute("SELECT match_confidence FROM dim_area WHERE scraped_area_id = ? LIMIT 1", [area_id]).fetchone()

    return {
        "area_id": area_id, "name": name, "area_type": area_type,
        "community_key": f"s{area_id}",
        "has_dld_link": bool(match_confidence and match_confidence[0] != "scraped_only"),
        "breadcrumb": breadcrumb,
        "profile": _area_profile(con, area_id),
        "livability": _livability_panel(con, area_id),
        "period": window.label,
        "own_stats": own_stats,
        "subtree_stats": subtree_stats,
        "child_count": len(children_rows),
        "children": children,
    }
