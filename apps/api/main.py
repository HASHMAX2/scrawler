from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.db import close_shared_connection, get_shared_connection
from ingestion import warehouse
from apps.api.routers import (
    areas,
    communities,
    compare,
    construction_watch,
    data_quality,
    decision_engine,
    developers,
    explorer,
    import_data,
    map_router,
    opportunities,
    overview,
    projects,
    pulse,
    reels,
    rentals,
    sales,
    search,
    signals,
    supply,
    unit_types,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    con = get_shared_connection()
    warehouse.ensure_schema(con)
    warehouse.attach_scraped_db(con)
    yield
    close_shared_connection()


app = FastAPI(title="Dubai Real Estate Intelligence API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router, prefix="/api/overview", tags=["overview"])
app.include_router(areas.router, prefix="/api/areas", tags=["areas"])
app.include_router(communities.router, prefix="/api/communities", tags=["communities"])
app.include_router(sales.router, prefix="/api/sales", tags=["sales"])
app.include_router(rentals.router, prefix="/api/rentals", tags=["rentals"])
app.include_router(unit_types.router, prefix="/api/unit-types", tags=["unit-types"])
app.include_router(compare.router, prefix="/api/compare", tags=["compare"])
app.include_router(data_quality.router, prefix="/api/data-quality", tags=["data-quality"])
app.include_router(explorer.router, prefix="/api/explorer", tags=["explorer"])
app.include_router(map_router.router, prefix="/api/map", tags=["map"])
app.include_router(import_data.router, prefix="/api/import", tags=["import"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(developers.router, prefix="/api/developers", tags=["developers"])
app.include_router(supply.router, prefix="/api/supply", tags=["supply"])
app.include_router(opportunities.router, prefix="/api/opportunities", tags=["opportunities"])
app.include_router(pulse.router, prefix="/api/pulse", tags=["pulse"])
app.include_router(signals.router, prefix="/api/signals", tags=["signals"])
app.include_router(decision_engine.router, prefix="/api/decision-engine", tags=["decision-engine"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(construction_watch.router, prefix="/api/construction-watch", tags=["construction-watch"])
app.include_router(reels.router, prefix="/api/reels", tags=["reels"])


@app.get("/api/health")
def health():
    return {"status": "ok"}
