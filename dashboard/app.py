"""Lightweight local dashboard (brief §18-22). FastAPI + server-rendered Jinja2
templates — no SPA framework, no build step, just `python dashboard.py`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard import queries as q
from scraper import exporter

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "data" / "propsearch.db"
EXPORT_DIR = ROOT / "exports"

app = FastAPI(title="Propsearch Dashboard")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, always closed afterwards
    (each route previously opened a connection via a plain function call and never
    closed it — harmless for a quick manual check, but a real leak under sustained
    use)."""
    conn = q.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/", response_class=HTMLResponse)
def home(request: Request, conn: sqlite3.Connection = Depends(db)):
    job = q.latest_job(conn)
    queue = q.queue_counts(conn, job["id"]) if job else {}
    overview = q.db_overview(conn)
    status = q.status_breakdown(conn)
    quality = q.data_quality(conn)
    discoveries = q.recent_discoveries(conn, limit=15)
    changes = q.recent_changes(conn, limit=15)
    jobs = q.all_jobs(conn)
    health = q.crawl_health(conn)
    return templates.TemplateResponse(request, "index.html", {
        "job": job, "queue": queue, "overview": overview,
        "status": status, "quality": quality, "discoveries": discoveries,
        "changes": changes, "jobs": jobs, "elapsed": q.elapsed_label(job) if job else "-",
        "db_exists": DB_PATH.exists(), "health": health,
    })


@app.get("/areas", response_class=HTMLResponse)
def areas_list(request: Request, search: str | None = None, conn: sqlite3.Connection = Depends(db)):
    areas = q.list_areas(conn, search=search)
    return templates.TemplateResponse(request, "areas.html", {"areas": areas, "search": search or ""})


@app.get("/areas/{area_id}", response_class=HTMLResponse)
def area_detail(request: Request, area_id: int, conn: sqlite3.Connection = Depends(db)):
    area = q.get_area(conn, area_id)
    if area is None:
        return RedirectResponse("/areas")
    status = q.status_breakdown(conn, area_id=area_id)
    quality = q.data_quality(conn, area_id=area_id)
    coverage = q.area_unit_coverage(conn, area_id)
    subcommunities = q.sub_communities_for(conn, area_id)
    developments = q.list_developments(conn, area_id=area_id, limit=500)
    return templates.TemplateResponse(request, "area_detail.html", {
        "area": area, "status": status, "quality": quality,
        "coverage": coverage, "subcommunities": subcommunities, "developments": developments,
    })


@app.get("/developments", response_class=HTMLResponse)
def developments_list(
    request: Request,
    search: str | None = None,
    area_id: int | None = None,
    developer_id: int | None = None,
    status: str | None = None,
    dev_type: str | None = None,
    completion_year: str | None = None,
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(db),
):
    page_size = 100
    filters = dict(area_id=area_id, developer_id=developer_id, status=status, dev_type=dev_type,
                    search=search, completion_year=completion_year)
    developments = q.list_developments(conn, limit=page_size, offset=(page - 1) * page_size, **filters)
    total = q.count_developments(conn, **filters)
    querystring = "&".join(f"{k}={v}" for k, v in filters.items() if v)
    return templates.TemplateResponse(request, "developments.html", {
        "developments": developments, "areas": q.list_areas(conn),
        "developers": q.all_developers(conn), "statuses": q.all_statuses(conn),
        "dev_types": q.all_dev_types(conn), "filters": filters, "page": page,
        "total": total, "total_pages": max(1, -(-total // page_size)), "querystring": querystring,
    })


@app.get("/developments/{dev_id}", response_class=HTMLResponse)
def development_detail(request: Request, dev_id: int, conn: sqlite3.Connection = Depends(db)):
    dev = q.get_development(conn, dev_id)
    if dev is None:
        return RedirectResponse("/developments")
    buildings = q.buildings_for(conn, dev_id)
    unit_supply = q.unit_supply_for(conn, dev_id)
    transactions = q.transactions_for(conn, dev_id)
    companies = q.construction_history_for(conn, dev_id)
    milestones = q.milestones_for(conn, dev_id)
    master = q.master_development_of(conn, dev)
    sub_devs = q.sub_developments_of(conn, dev_id)
    changes = q.change_log_for(conn, "development", dev_id)
    return templates.TemplateResponse(request, "development_detail.html", {
        "dev": dev, "buildings": buildings, "unit_supply": unit_supply,
        "transactions": transactions, "companies": companies, "milestones": milestones,
        "master": master, "sub_devs": sub_devs, "changes": changes,
    })


@app.get("/export", response_class=HTMLResponse)
def export_page(request: Request):
    return templates.TemplateResponse(request, "export.html", {"tables": exporter.TABLES})


@app.get("/export/combined")
def export_combined():
    path = exporter.export_combined_json(DB_PATH, EXPORT_DIR / "combined.json")
    return FileResponse(path, filename="combined.json", media_type="application/json")


# NOTE: the "/all" routes must be registered before the "/{table}" routes below,
# otherwise FastAPI would match "all" as a table name first and 404/redirect.
@app.get("/export/csv/all")
def export_csv_all():
    paths = exporter.export_csv(DB_PATH, EXPORT_DIR)
    return templates_ok_message(paths)


@app.get("/export/json/all")
def export_json_all():
    paths = exporter.export_json(DB_PATH, EXPORT_DIR)
    return templates_ok_message(paths)


def templates_ok_message(paths):
    names = ", ".join(p.name for p in paths)
    return HTMLResponse(
        f"<p>Wrote {len(paths)} files to the <code>exports/</code> folder: {names}</p>"
        f"<p><a href='/export'>Back to export page</a></p>"
    )


@app.get("/export/csv/{table}")
def export_csv_table(table: str):
    if table not in exporter.TABLES:
        return RedirectResponse("/export")
    paths = exporter.export_csv(DB_PATH, EXPORT_DIR, tables=[table])
    return FileResponse(paths[0], filename=f"{table}.csv", media_type="text/csv")


@app.get("/export/json/{table}")
def export_json_table(table: str):
    if table not in exporter.TABLES:
        return RedirectResponse("/export")
    paths = exporter.export_json(DB_PATH, EXPORT_DIR, tables=[table])
    return FileResponse(paths[0], filename=f"{table}.json", media_type="application/json")
