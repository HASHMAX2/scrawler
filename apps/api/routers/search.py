"""Global project/building autocomplete search.

Searches the persisted master-project/building hierarchy (dim_master_project
+ dim_project), never a runtime string scan — see ingestion.warehouse's
build_dim_project_hierarchy for how that hierarchy is built. Ranking is
delegated to apps.api.analytics.search_rank (pure, unit-tested), so a master
project outranks its own buildings on an exact-name query while a specific
building's exact name still wins if that's what was typed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.search_rank import SearchCandidate, rank_candidates
from apps.api.db import db
from ingestion.normalize import canonical_key

router = APIRouter()


@router.get("/suggest")
def suggest(q: str, limit: int = 12, con=Depends(db)):
    query = q.strip()
    if len(query) < 2:
        return {"query": q, "items": []}
    query_key = canonical_key(query)

    masters = con.execute(
        "SELECT master_project_id, display_name, canonical_key, slug, building_count, developer_name, area_name FROM dim_master_project"
    ).fetchall()
    buildings = con.execute("""
        SELECT dp.project_id, dp.dld_project_name, dp.canonical_key, dp.building_slug, dp.master_project_id, mp.display_name, mp.slug
        FROM dim_project dp
        JOIN dim_master_project mp ON dp.master_project_id = mp.master_project_id
        WHERE dp.dld_project_name IS NOT NULL AND dp.building_slug IS NOT NULL
    """).fetchall()
    overrides = dict(
        con.execute("SELECT raw_project_canonical_key, override_master_key FROM master_project_overrides").fetchall()
    )

    candidates: list[SearchCandidate] = []
    for mpid, name, ck, slug, bcount, dev, area in masters:
        if bcount > 1:
            subtitle = f"Master Project · {bcount} buildings"
        else:
            subtitle = "Project" + (f" · {dev}" if dev else (f" · {area}" if area else ""))
        candidates.append(SearchCandidate(id=mpid, kind="master", display_name=name, canonical_key=ck, subtitle=subtitle, slug=slug))
    for pid, raw_name, ck, bslug, mpid, mname, mslug in buildings:
        candidates.append(SearchCandidate(
            id=pid, kind="building", display_name=raw_name.strip(), canonical_key=ck,
            subtitle=f"Building · {mname}", slug=bslug, master_slug=mslug,
        ))

    ranked = rank_candidates(query_key, candidates, overrides)[:limit]
    return {
        "query": q,
        "items": [
            {
                "id": r.candidate.id, "kind": r.candidate.kind, "name": r.candidate.display_name,
                "subtitle": r.candidate.subtitle, "slug": r.candidate.slug, "master_slug": r.candidate.master_slug,
            }
            for r in ranked
        ],
    }
