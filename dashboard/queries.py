"""All dashboard numbers are computed here, straight from SQLite, on every request.
Nothing in this module is a hardcoded figure — that's a hard requirement from the
brief (§19: "Always calculate dashboard numbers from scraped database records. Never
hardcode them.").
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _one(conn, sql, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row and row[0] is not None else 0


# -- crawl overview ---------------------------------------------------------

def latest_job(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM crawl_jobs ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def all_jobs(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM crawl_jobs ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def queue_counts(conn: sqlite3.Connection, job_id: int) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) c FROM crawl_queue WHERE job_id=? GROUP BY status", (job_id,)
    ).fetchall()
    return {r["status"]: r["c"] for r in rows}


def recent_errors(conn: sqlite3.Connection, job_id: int, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM crawl_errors WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)
    ).fetchall()
    return [dict(r) for r in rows]


def elapsed_label(job: dict) -> str:
    if not job:
        return "-"
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    start = time.strptime(job["started_at"], fmt)
    end_str = job["finished_at"] or time.strftime(fmt, time.gmtime())
    end = time.strptime(end_str, fmt)
    seconds = int(time.mktime(end) - time.mktime(start))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


# -- database overview --------------------------------------------------

def db_overview(conn: sqlite3.Connection) -> dict:
    return dict(
        areas=_one(conn, "SELECT COUNT(*) FROM areas"),
        sub_communities=_one(conn, "SELECT COUNT(*) FROM sub_communities"),
        developments=_one(conn, "SELECT COUNT(*) FROM developments WHERE is_active=1"),
        developments_inactive=_one(conn, "SELECT COUNT(*) FROM developments WHERE is_active=0"),
        buildings=_one(conn, "SELECT COUNT(*) FROM buildings"),
        developers=_one(conn, "SELECT COUNT(*) FROM developers"),
        known_residential_units=_one(
            conn, "SELECT COALESCE(SUM(total_units),0) FROM developments WHERE is_active=1 AND total_units IS NOT NULL"
        ),
        transactions=_one(conn, "SELECT COUNT(*) FROM transactions"),
        amenities=_one(conn, "SELECT COUNT(*) FROM amenities"),
        schools=_one(conn, "SELECT COUNT(*) FROM schools"),
        villas=_one(
            conn,
            "SELECT COUNT(*) FROM developments WHERE is_active=1 AND "
            "(building_type_raw LIKE '%villa%' OR building_type_raw LIKE '%Villa%')",
        ),
        townhouses=_one(
            conn,
            "SELECT COUNT(*) FROM developments WHERE is_active=1 AND "
            "(building_type_raw LIKE '%townhouse%' OR building_type_raw LIKE '%Townhouse%')",
        ),
    )


def _area_children_map(conn: sqlite3.Connection) -> dict[int, list[int]]:
    """Areas only carry `parent_area_name` (free text from Propsearch, matched against
    `areas.name` — there's no dedicated FK) rather than a parent id, because that's
    all the site's own pages expose. Build a name->id lookup plus a parent->children
    id map once per request; cheap at this project's scale (hundreds of areas, not
    hundreds of thousands) and much simpler than a correlated recursive CTE per row.
    """
    rows = conn.execute("SELECT id, name, parent_area_name FROM areas").fetchall()
    name_to_id = {r["name"]: r["id"] for r in rows}
    children: dict[int, list[int]] = {}
    for r in rows:
        parent_id = name_to_id.get(r["parent_area_name"])
        if parent_id is not None and parent_id != r["id"]:
            children.setdefault(parent_id, []).append(r["id"])
    return children


def rollup_area_ids(conn: sqlite3.Connection, area_id: int) -> list[int]:
    """This area's id plus every descendant reachable via `parent_area_name` chains
    (e.g. Jumeirah Village Circle -> JVC District 11 -> ...). Propsearch's own
    development pages tag their `Area` field at the district/sub-community level, not
    the top-level community, so a top-level area's own dashboard numbers must roll up
    its whole sub-tree to match what the brief's example area-detail page expects
    (§19) — a naive `WHERE area_id = ?` alone would show near-zero for JVC itself.
    """
    children = _area_children_map(conn)
    ids = [area_id]
    frontier = [area_id]
    seen = {area_id}
    while frontier:
        next_frontier = []
        for aid in frontier:
            for child in children.get(aid, []):
                if child not in seen:
                    seen.add(child)
                    ids.append(child)
                    next_frontier.append(child)
        frontier = next_frontier
    return ids


def status_breakdown(conn: sqlite3.Connection, area_id: int | None = None) -> dict:
    where = "WHERE is_active=1"
    params: tuple = ()
    if area_id:
        ids = rollup_area_ids(conn, area_id)
        where += f" AND area_id IN ({','.join('?' * len(ids))})"
        params = tuple(ids)
    rows = conn.execute(
        f"SELECT normalized_status, COUNT(*) c FROM developments {where} GROUP BY normalized_status", params
    ).fetchall()
    out = {r["normalized_status"] or "other": r["c"] for r in rows}
    for key in ("completed", "under_construction", "planned", "announced", "on_hold", "delayed", "cancelled", "other"):
        out.setdefault(key, 0)
    return out


def data_quality(conn: sqlite3.Connection, area_id: int | None = None) -> dict:
    where = "WHERE is_active=1"
    params: tuple = ()
    if area_id:
        ids = rollup_area_ids(conn, area_id)
        where += f" AND area_id IN ({','.join('?' * len(ids))})"
        params = tuple(ids)
    total = _one(conn, f"SELECT COUNT(*) FROM developments {where}", params)
    with_units = _one(conn, f"SELECT COUNT(*) FROM developments {where} AND total_units IS NOT NULL", params)
    with_developer = _one(conn, f"SELECT COUNT(*) FROM developments {where} AND developer_id IS NOT NULL", params)
    with_location = _one(
        conn, f"SELECT COUNT(*) FROM developments {where} AND latitude IS NOT NULL AND longitude IS NOT NULL", params
    )
    with_status = _one(conn, f"SELECT COUNT(*) FROM developments {where} AND raw_status IS NOT NULL", params)
    return dict(
        total=total,
        with_unit_count=with_units, missing_unit_count=total - with_units,
        with_developer=with_developer, missing_developer=total - with_developer,
        with_location=with_location, missing_location=total - with_location,
        with_status=with_status, missing_status=total - with_status,
    )


def recent_discoveries(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM change_log WHERE change_kind='new_record' ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def recent_changes(conn: sqlite3.Connection, limit: int = 25) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM change_log WHERE change_kind IN ('field_changed','disappeared') "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def crawl_health(conn: sqlite3.Connection) -> dict:
    """Politeness/compliance panel: today's request count (crawl_budget has no stored
    limit to compare against — --max-requests-per-day is a CLI-only runtime flag, not
    persisted, so there's nothing true to show as "budget" without fabricating a
    value), the most recent block/error, and the mall/landmark classification counts.
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())
    requests_today = _one(conn, "SELECT requests_used FROM crawl_budget WHERE date = ?", (today,))
    last_error_row = conn.execute("SELECT * FROM crawl_errors ORDER BY id DESC LIMIT 1").fetchone()
    area_type_counts = {
        r["area_type"]: r["c"]
        for r in conn.execute("SELECT area_type, COUNT(*) c FROM areas GROUP BY area_type").fetchall()
    }
    return dict(
        requests_today=requests_today,
        last_error=dict(last_error_row) if last_error_row else None,
        mall_count=area_type_counts.get("mall", 0),
        landmark_count=area_type_counts.get("landmark", 0),
        mentioned_places=_one(conn, "SELECT COUNT(*) FROM mentioned_places"),
        entity_aliases=_one(conn, "SELECT COUNT(*) FROM entity_aliases"),
    )


# -- areas ----------------------------------------------------------------

def list_areas(conn: sqlite3.Connection, search: str | None = None) -> list[dict]:
    sql = "SELECT * FROM areas"
    params: tuple = ()
    if search:
        sql += " WHERE name LIKE ?"
        params = (f"%{search}%",)
    areas = [dict(r) for r in conn.execute(sql, params).fetchall()]

    # Rollup counts (this area + all descendants), computed once for every area in a
    # single pass rather than a correlated subquery per row — see rollup_area_ids.
    direct_counts = {
        r["area_id"]: r["c"] for r in conn.execute(
            "SELECT area_id, COUNT(*) c FROM developments WHERE is_active=1 AND area_id IS NOT NULL "
            "GROUP BY area_id"
        ).fetchall()
    }
    children = _area_children_map(conn)
    memo: dict[int, int] = {}

    def rollup_count(area_id: int, _stack: frozenset = frozenset()) -> int:
        if area_id in memo:
            return memo[area_id]
        if area_id in _stack:
            return 0  # defensive: guards against a malformed cyclical parent chain
        total = direct_counts.get(area_id, 0)
        for child in children.get(area_id, []):
            total += rollup_count(child, _stack | {area_id})
        memo[area_id] = total
        return total

    for area in areas:
        area["development_count"] = rollup_count(area["id"])
    areas.sort(key=lambda a: (-a["development_count"], a["name"]))
    return areas


def get_area(conn: sqlite3.Connection, area_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM areas WHERE id=?", (area_id,)).fetchone()
    return dict(row) if row else None


def area_unit_coverage(conn: sqlite3.Connection, area_id: int) -> dict:
    ids = rollup_area_ids(conn, area_id)
    placeholders = ",".join("?" * len(ids))
    params = tuple(ids)
    total = _one(conn, f"SELECT COUNT(*) FROM developments WHERE area_id IN ({placeholders}) AND is_active=1", params)
    known = _one(
        conn,
        f"SELECT COUNT(*) FROM developments WHERE area_id IN ({placeholders}) AND is_active=1 AND total_units IS NOT NULL",
        params,
    )
    residential_units = _one(
        conn,
        f"SELECT COALESCE(SUM(total_units),0) FROM developments WHERE area_id IN ({placeholders}) AND is_active=1 "
        "AND total_units IS NOT NULL",
        params,
    )
    villas = _one(
        conn,
        f"SELECT COUNT(*) FROM developments WHERE area_id IN ({placeholders}) AND is_active=1 AND building_type_raw LIKE '%illa%'",
        params,
    )
    townhouses = _one(
        conn,
        f"SELECT COUNT(*) FROM developments WHERE area_id IN ({placeholders}) AND is_active=1 AND building_type_raw LIKE '%ownhouse%'",
        params,
    )
    return dict(total=total, known_units=known, residential_units=residential_units,
                villas=villas, townhouses=townhouses)


def sub_communities_for(conn: sqlite3.Connection, area_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM sub_communities WHERE parent_area_id=? ORDER BY name", (area_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# -- developments -----------------------------------------------------------

def list_developments(conn: sqlite3.Connection, area_id: int | None = None, developer_id: int | None = None,
                       status: str | None = None, dev_type: str | None = None, search: str | None = None,
                       completion_year: str | None = None, limit: int = 200, offset: int = 0) -> list[dict]:
    sql = (
        "SELECT d.*, a.name AS area_name, dv.name AS developer_name "
        "FROM developments d LEFT JOIN areas a ON d.area_id=a.id "
        "LEFT JOIN developers dv ON d.developer_id=dv.id WHERE d.is_active=1"
    )
    params: list = []
    if area_id:
        # Rolled up to include sub-communities/districts — Propsearch tags a
        # development's Area at the district level, so a top-level area's own filter
        # must include its children to match what a user picking that area expects.
        ids = rollup_area_ids(conn, area_id)
        sql += f" AND d.area_id IN ({','.join('?' * len(ids))})"
        params.extend(ids)
    if developer_id:
        sql += " AND d.developer_id=?"
        params.append(developer_id)
    if status:
        sql += " AND d.normalized_status=?"
        params.append(status)
    if dev_type:
        sql += " AND d.building_type_raw LIKE ?"
        params.append(f"%{dev_type}%")
    if search:
        sql += " AND d.name LIKE ?"
        params.append(f"%{search}%")
    if completion_year:
        sql += " AND (d.estimated_completion_date LIKE ? OR d.actual_completion_date LIKE ?)"
        params.extend([f"{completion_year}%", f"{completion_year}%"])
    sql += " ORDER BY d.last_seen DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def count_developments(conn: sqlite3.Connection, **filters) -> int:
    rows = list_developments(conn, limit=10_000_000, offset=0, **filters)
    return len(rows)


def get_development(conn: sqlite3.Connection, dev_id: int) -> dict | None:
    row = conn.execute(
        "SELECT d.*, a.name AS area_name, dv.name AS developer_name, dv.url AS developer_url "
        "FROM developments d LEFT JOIN areas a ON d.area_id=a.id "
        "LEFT JOIN developers dv ON d.developer_id=dv.id WHERE d.id=?",
        (dev_id,),
    ).fetchone()
    return dict(row) if row else None


def get_development_by_slug(conn: sqlite3.Connection, url: str) -> dict | None:
    row = conn.execute(
        "SELECT d.*, a.name AS area_name, dv.name AS developer_name, dv.url AS developer_url "
        "FROM developments d LEFT JOIN areas a ON d.area_id=a.id "
        "LEFT JOIN developers dv ON d.developer_id=dv.id WHERE d.url=?",
        (url,),
    ).fetchone()
    return dict(row) if row else None


def buildings_for(conn: sqlite3.Connection, dev_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM buildings WHERE development_id=? ORDER BY name", (dev_id,)
    ).fetchall()]


def unit_supply_for(conn: sqlite3.Connection, dev_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM unit_supply WHERE development_id=?", (dev_id,)).fetchone()
    return dict(row) if row else None


def transactions_for(conn: sqlite3.Connection, dev_id: int, limit: int = 50) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM transactions WHERE development_id=? ORDER BY transaction_date DESC LIMIT ?",
        (dev_id, limit),
    ).fetchall()]


def construction_history_for(conn: sqlite3.Connection, dev_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM construction_history WHERE development_id=?", (dev_id,)
    ).fetchall()]


def milestones_for(conn: sqlite3.Connection, dev_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM construction_milestones WHERE development_id=?", (dev_id,)
    ).fetchall()]


def master_development_of(conn: sqlite3.Connection, dev: dict) -> dict | None:
    if not dev.get("master_development_id"):
        return None
    return get_development(conn, dev["master_development_id"])


def sub_developments_of(conn: sqlite3.Connection, dev_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM developments WHERE master_development_id=?", (dev_id,)
    ).fetchall()]


def change_log_for(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM change_log WHERE entity_type=? AND entity_id=? ORDER BY id DESC",
        (entity_type, entity_id),
    ).fetchall()]


# -- filter option lists -----------------------------------------------------

def all_developers(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, name FROM developers ORDER BY name"
    ).fetchall()]


def all_statuses(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT normalized_status FROM developments WHERE normalized_status IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def all_dev_types(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT building_type_raw FROM developments WHERE building_type_raw IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]
