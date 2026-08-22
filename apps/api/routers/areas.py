from __future__ import annotations

import pandas as pd
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


def _effective_stats(direct: dict, project_matched: dict) -> dict:
    """DLD's own AREA_EN field resolves some areas (Silicon Oasis, Dubai
    South, JLT, ...) far more sparsely than the project-matched join does —
    e.g. Silicon Oasis shows 1 direct sale vs 240 recovered via project
    matching. Neither source is reliably bigger for every area, and sales
    vs rentals can disagree even within the same area, so pick whichever
    source has the higher count independently for sales and for rentals,
    keeping that source's own price/rent paired together so yield stays
    internally consistent rather than mixing sources.
    """
    use_pm_sales = project_matched["sales_count"] > direct["sales_count"]
    use_pm_rentals = project_matched["rental_count"] > direct["rental_count"]
    sales_count = project_matched["sales_count"] if use_pm_sales else direct["sales_count"]
    sales_value = project_matched["sales_value"] if use_pm_sales else direct["sales_value"]
    median_price = project_matched["median_price"] if use_pm_sales else direct["median_price"]
    rental_count = project_matched["rental_count"] if use_pm_rentals else direct["rental_count"]
    median_rent = project_matched["median_rent"] if use_pm_rentals else direct["median_rent"]
    return {
        "sales_count": sales_count, "sales_value": sales_value, "median_price": median_price,
        "rental_count": rental_count, "median_rent": median_rent,
        "estimated_gross_yield_pct": estimated_gross_yield(median_rent, median_price),
        "data_source": {"sales": "project_matched" if use_pm_sales else "dld_direct", "rentals": "project_matched" if use_pm_rentals else "dld_direct"},
    }


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


def _project_matched_stats(con, area_ids: list[int], window) -> dict:
    """DLD's own AREA_EN field only ever reports the broad community (e.g.
    "Jumeirah Village Circle"), never the sub-district — so _rollup_stats is
    near-zero for every sub-area. But DLD's PROJECT_EN (building name) can be
    entity-resolved to a specific scraped development, and that development
    carries Propsearch's own precise sub-district area_id (confirmed: 943 of
    JVC's ~960 scraped developments are attached to a specific JVC District,
    not to JVC itself). Joining fact_sales/fact_rentals -> dim_project ->
    scraped.developments.area_id recovers real sub-community-level sales,
    covering ~55% of all sales rows overall. This is a different, looser
    methodology than _rollup_stats (subject to Propsearch's own project-name
    matching, not DLD's area label) — kept as a separate field rather than
    merged into own_stats/subtree_stats so it never silently disagrees with
    the community-level totals shown on the Communities page.
    """
    if not area_ids:
        return {
            "sales_count": 0, "sales_value": None, "median_price": None,
            "rental_count": 0, "median_rent": None, "estimated_gross_yield_pct": None,
        }
    placeholders = ", ".join(["?"] * len(area_ids))
    sales = con.execute(
        f"""
        SELECT count(*), sum(fs.trans_value_aed), median(fs.trans_value_aed)
        FROM fact_sales fs
        JOIN dim_project dp ON fs.project_id = dp.project_id
        JOIN scraped.developments d ON dp.matched_development_id = d.id
        WHERE d.area_id IN ({placeholders}) AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
        """,
        area_ids + [window.current_start, window.current_end],
    ).fetchone()
    rentals = con.execute(
        f"""
        SELECT count(*), median(fr.annual_amount_aed)
        FROM fact_rentals fr
        JOIN dim_project dp ON fr.project_id = dp.project_id
        JOIN scraped.developments d ON dp.matched_development_id = d.id
        WHERE d.area_id IN ({placeholders}) AND fr.registration_date BETWEEN ? AND ?
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

    Originally built as a per-root loop (_subtree_ids + _rollup_stats +
    _child_count + _project_matched_stats, ~6 queries x 92 roots = ~550
    sequential round trips against fact_sales/fact_rentals) — that took
    ~17s per request. Since the area tree is a strict partition (every
    scraped area belongs to exactly one top-level root), the whole thing
    collapses into: one read of the tree to compute root membership in
    Python, then one GROUP-BY query per fact table joined against that
    membership map. Same response shape, ~5 queries total instead of ~550.
    """
    window = resolve_period(con, period)
    all_areas = con.execute(
        "SELECT id, name, parent_area_name, area_type, hero_image_url, also_known_as FROM scraped.areas"
    ).fetchall()
    by_parent: dict[str, list[tuple]] = {}
    for row in all_areas:
        by_parent.setdefault(row[2], []).append(row)

    roots = sorted(
        (r for r in by_parent.get("Dubai", []) if r[3] == "community"),
        key=lambda r: r[1],
    )

    root_of: dict[int, int] = {}
    subtree_size: dict[int, int] = {}
    child_count: dict[int, int] = {}
    for root_id, root_name, *_ in roots:
        child_count[root_id] = sum(1 for c in by_parent.get(root_name, []) if c[3] == "community")
        stack: list[tuple[int, str, int]] = [(root_id, root_name, 0)]
        count = 0
        while stack:
            aid, aname, depth = stack.pop()
            root_of[aid] = root_id
            count += 1
            if depth >= MAX_DEPTH:
                continue
            for child in by_parent.get(aname, []):
                if child[3] == "community":
                    stack.append((child[0], child[1], depth + 1))
        subtree_size[root_id] = count

    root_map_df = pd.DataFrame(list(root_of.items()), columns=["scraped_area_id", "root_area_id"])
    con.register("_root_map", root_map_df)
    try:
        sales_by_root = {
            r[0]: r[1:]
            for r in con.execute(
                """
                SELECT rm.root_area_id, count(*), sum(fs.trans_value_aed), median(fs.trans_value_aed)
                FROM fact_sales fs
                JOIN dim_area da ON fs.area_id = da.area_id
                JOIN _root_map rm ON da.scraped_area_id = rm.scraped_area_id
                WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
                GROUP BY 1
                """,
                [window.current_start, window.current_end],
            ).fetchall()
        }
        rentals_by_root = {
            r[0]: r[1:]
            for r in con.execute(
                """
                SELECT rm.root_area_id, count(*), median(fr.annual_amount_aed)
                FROM fact_rentals fr
                JOIN dim_area da ON fr.area_id = da.area_id
                JOIN _root_map rm ON da.scraped_area_id = rm.scraped_area_id
                WHERE fr.registration_date BETWEEN ? AND ?
                GROUP BY 1
                """,
                [window.current_start, window.current_end],
            ).fetchall()
        }
        proj_sales_by_root = {
            r[0]: r[1:]
            for r in con.execute(
                """
                SELECT rm.root_area_id, count(*), sum(fs.trans_value_aed), median(fs.trans_value_aed)
                FROM fact_sales fs
                JOIN dim_project dp ON fs.project_id = dp.project_id
                JOIN scraped.developments d ON dp.matched_development_id = d.id
                JOIN _root_map rm ON d.area_id = rm.scraped_area_id
                WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
                GROUP BY 1
                """,
                [window.current_start, window.current_end],
            ).fetchall()
        }
        proj_rentals_by_root = {
            r[0]: r[1:]
            for r in con.execute(
                """
                SELECT rm.root_area_id, count(*), median(fr.annual_amount_aed)
                FROM fact_rentals fr
                JOIN dim_project dp ON fr.project_id = dp.project_id
                JOIN scraped.developments d ON dp.matched_development_id = d.id
                JOIN _root_map rm ON d.area_id = rm.scraped_area_id
                WHERE fr.registration_date BETWEEN ? AND ?
                GROUP BY 1
                """,
                [window.current_start, window.current_end],
            ).fetchall()
        }
    finally:
        con.unregister("_root_map")

    items = []
    for area_id, name, _parent, _atype, hero, aka in roots:
        s = sales_by_root.get(area_id, (0, None, None))
        r = rentals_by_root.get(area_id, (0, None))
        ps = proj_sales_by_root.get(area_id, (0, None, None))
        pr = proj_rentals_by_root.get(area_id, (0, None))
        direct = {"sales_count": s[0], "sales_value": s[1], "median_price": s[2], "rental_count": r[0], "median_rent": r[1]}
        project_matched = {"sales_count": ps[0], "sales_value": ps[1], "median_price": ps[2], "rental_count": pr[0], "median_rent": pr[1]}

        items.append({
            "area_id": area_id, "name": name, "hero_image_url": hero, "also_known_as": aka,
            "child_count": child_count[area_id], "descendant_count": subtree_size[area_id] - 1,
            "project_matched_stats": {
                **project_matched,
                "estimated_gross_yield_pct": estimated_gross_yield(pr[1], ps[2]),
            },
            **_effective_stats(direct, project_matched),
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

    own_project_matched_stats = _project_matched_stats(con, [area_id], window)
    own_direct = _rollup_stats(con, [area_id], window)
    own_stats = {**own_direct, **_effective_stats(own_direct, own_project_matched_stats)}
    subtree = _subtree_ids(con, area_id)
    if len(subtree) > 1:
        subtree_project_matched_stats = _project_matched_stats(con, subtree, window)
        subtree_direct = _rollup_stats(con, subtree, window)
        subtree_stats = {**subtree_direct, **_effective_stats(subtree_direct, subtree_project_matched_stats)}
    else:
        subtree_stats = own_stats
        subtree_project_matched_stats = own_project_matched_stats

    children_rows = con.execute(
        """
        SELECT id, name, hero_image_url FROM scraped.areas
        WHERE parent_area_name = ? AND area_type = 'community' ORDER BY name
        """,
        [name],
    ).fetchall()
    children = []
    for cid, cname, chero in children_rows:
        c_stats = _rollup_stats(con, [cid], window)
        c_project_stats = _project_matched_stats(con, [cid], window)
        children.append({
            "area_id": cid, "name": cname, "hero_image_url": chero,
            "community_key": f"s{cid}", "child_count": _child_count(con, cname),
            "project_matched_stats": c_project_stats,
            **_effective_stats(c_stats, c_project_stats),
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
        "own_project_matched_stats": own_project_matched_stats,
        "subtree_stats": subtree_stats,
        "subtree_project_matched_stats": subtree_project_matched_stats,
        "child_count": len(children_rows),
        "children": children,
    }


@router.get("/{area_id}/projects")
def area_projects(area_id: int, period: str = "90d", limit: int = 12, con=Depends(db)):
    """Master projects with at least one building physically located in this
    area's subtree, via the same building-level attribution as
    _project_matched_stats (scraped.developments.area_id). Powers the
    Intelligence Map's Area -> Project drilldown — no existing endpoint
    lists projects scoped to an area, so this is purely additive.
    """
    window = resolve_period(con, period)
    subtree = _subtree_ids(con, area_id)
    if not subtree:
        return {"period": window.label, "items": []}
    area_placeholders = ", ".join(["?"] * len(subtree))
    master_ids = [
        r[0] for r in con.execute(
            f"""
            SELECT DISTINCT dp.master_project_id
            FROM dim_project dp JOIN scraped.developments d ON dp.matched_development_id = d.id
            WHERE d.area_id IN ({area_placeholders}) AND dp.master_project_id IS NOT NULL
            """,
            subtree,
        ).fetchall()
    ]
    if not master_ids:
        return {"period": window.label, "items": []}
    id_placeholders = ", ".join(["?"] * len(master_ids))

    sales = {
        r[0]: r[1:] for r in con.execute(
            f"""
            SELECT dp.master_project_id, count(*), median(fs.trans_value_aed), median(fs.price_per_sqft_aed)
            FROM fact_sales fs JOIN dim_project dp ON fs.project_id = dp.project_id
            WHERE dp.master_project_id IN ({id_placeholders}) AND fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales'
            GROUP BY 1
            """,
            master_ids + [window.current_start, window.current_end],
        ).fetchall()
    }
    rentals = {
        r[0]: r[1:] for r in con.execute(
            f"""
            SELECT dp.master_project_id, count(*), median(fr.annual_amount_aed)
            FROM fact_rentals fr JOIN dim_project dp ON fr.project_id = dp.project_id
            WHERE dp.master_project_id IN ({id_placeholders}) AND fr.registration_date BETWEEN ? AND ?
            GROUP BY 1
            """,
            master_ids + [window.current_start, window.current_end],
        ).fetchall()
    }
    meta = con.execute(
        f"SELECT master_project_id, display_name, slug, developer_name, building_count FROM dim_master_project WHERE master_project_id IN ({id_placeholders})",
        master_ids,
    ).fetchall()

    items = []
    for mid, name, slug, dev, bcount in meta:
        s = sales.get(mid, (0, None, None))
        r = rentals.get(mid, (0, None))
        items.append({
            "master_project_id": mid, "name": name, "slug": slug, "developer_name": dev, "building_count": bcount,
            "sales_count": s[0], "median_price": s[1], "median_psf": s[2],
            "rental_count": r[0], "median_rent": r[1],
            "estimated_gross_yield_pct": estimated_gross_yield(r[1], s[1]),
        })
    items.sort(key=lambda x: x["sales_count"] + x["rental_count"], reverse=True)
    return {"period": window.label, "items": items[:limit]}
