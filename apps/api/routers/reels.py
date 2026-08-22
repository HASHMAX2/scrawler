"""Reel Intelligence Engine — turns the 235-entry Reel Master Library into
real, database-backed analysis rather than a static list of ideas.

Architecture (see analytics/reel_sources.py and analytics/reel_resolvers.py):
  reel_manifest.json (parsed from the source docx)
    -> classify_sources()  -> ready / partial / external + missing sources
    -> resolver_for()      -> one of a handful of reusable analytics resolvers
    -> RESOLVERS[type](con, period, params) -> real computed AnalysisResult

Never fabricates: a reel that needs data this warehouse doesn't have is
labeled partial/external with the exact missing source, not silently
answered with an invented number.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from apps.api.analytics.reel_resolvers import RESOLVERS
from apps.api.analytics.reel_sources import (
    FRANCHISES,
    SOURCE_LABELS,
    classify_sources,
    franchise_for_id,
    resolver_for,
)
from apps.api.db import db

router = APIRouter()

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "reel_manifest.json"
_RAW_MANIFEST: list[dict] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _enrich(reel: dict) -> dict:
    status, missing = classify_sources(reel["requiredSources"])
    return {
        **reel,
        "franchise": reel.get("franchise") or franchise_for_id(reel["id"]),
        "resolver": resolver_for(reel),
        "status": status,
        "missingSources": missing,
        "sourceLabels": [SOURCE_LABELS.get(s, s) for s in reel["requiredSources"]],
    }


MANIFEST: list[dict] = [_enrich(r) for r in _RAW_MANIFEST]
MANIFEST_BY_ID = {r["id"]: r for r in MANIFEST}
CATEGORIES = list(dict.fromkeys(r["category"] for r in MANIFEST))


@router.get("")
def list_reels(
    category: str | None = None,
    franchise: str | None = None,
    status: str | None = None,
    source: str | None = None,
    output: str | None = None,
    search: str | None = None,
):
    items = MANIFEST
    if category:
        items = [r for r in items if r["category"] == category]
    if franchise:
        items = [r for r in items if r["franchise"] == franchise]
    if status:
        items = [r for r in items if r["status"] == status]
    if source:
        items = [r for r in items if source in r["requiredSources"]]
    if output:
        items = [r for r in items if r["outputType"] == output]
    if search:
        q = search.strip().lower()
        items = [
            r for r in items
            if q in r["title"].lower() or q in r["category"].lower() or (r["franchise"] and q in r["franchise"].lower())
            or q in r["analyticalAngle"].lower() or any(q in s.lower() for s in r["requiredSources"])
        ]

    return {
        "total": len(MANIFEST),
        "filtered": len(items),
        "counts": {
            "ready": sum(1 for r in MANIFEST if r["status"] == "ready"),
            "partial": sum(1 for r in MANIFEST if r["status"] == "partial"),
            "external": sum(1 for r in MANIFEST if r["status"] == "external"),
        },
        "categories": [
            {"name": c, "count": sum(1 for r in MANIFEST if r["category"] == c),
             "readyCount": sum(1 for r in MANIFEST if r["category"] == c and r["status"] == "ready")}
            for c in CATEGORIES
        ],
        "items": items,
    }


@router.get("/franchises")
def list_franchises():
    out = []
    for name, spec in FRANCHISES.items():
        members = [r for r in MANIFEST if r["franchise"] == name]
        out.append({
            "name": name,
            "description": spec["description"],
            "count": len(members),
            "readyCount": sum(1 for r in members if r["status"] == "ready"),
        })
    return {"items": out}


@router.get("/{reel_id}")
def get_reel(reel_id: int):
    reel = MANIFEST_BY_ID.get(reel_id)
    if not reel:
        raise HTTPException(404, "Unknown reel id")
    return reel


@router.get("/{reel_id}/run")
def run_reel(reel_id: int, period: str = "90d", communityA: str | None = None, communityB: str | None = None,
             community: str | None = None, bedroom: str | None = None, budget: float | None = None,
             budgetMax: float | None = None, psfMax: float | None = None, project: str | None = None,
             limit: int = 15, con=Depends(db)):
    reel = MANIFEST_BY_ID.get(reel_id)
    if not reel:
        raise HTTPException(404, "Unknown reel id")

    if reel["status"] == "external":
        return {
            "reel": reel,
            "status": "external",
            "question": reel["title"],
            "period": period,
            "entities": [],
            "verdict": None,
            "reelReadyFacts": [],
            "whatIsInteresting": None,
            "caveat": f"This reel needs data this database does not have: {', '.join(SOURCE_LABELS.get(s, s) for s in reel['missingSources'])}.",
            "sources": reel["requiredSources"],
        }

    resolver = RESOLVERS.get(reel["resolver"])
    if not resolver:
        raise HTTPException(500, f"No resolver registered for type {reel['resolver']}")

    params = {
        "communityA": communityA, "communityB": communityB, "community": community,
        "bedroom": bedroom, "budget": budget, "budgetMax": budgetMax, "psfMax": psfMax,
        "project": project, "limit": limit,
    }
    if reel["resolver"] == "myth_test":
        # Myth reels borrow whichever generic resolver best tests the claim;
        # the manifest doesn't encode this per-reel, so default to the
        # community comparison / supply engines that cover most of the
        # documented myths, letting the caller override via `underlying`.
        params["underlying"] = "supply_analysis" if "supply" in reel["title"].lower() or "oversupplied" in reel["title"].lower() else "community_comparison"
        params["claim"] = reel["title"]

    result = resolver(con, period, params)
    return {"reel": reel, "status": reel["status"], **result}


# ---------------------------------------------------------------------------
# Ready to Make — surfaces real, currently-interesting findings from the
# existing opportunity/signal detectors (apps/api/routers/opportunities.py,
# apps/api/routers/signals.py) and maps each to the reel(s) it supports.
# Reuses those detectors rather than re-implementing anomaly detection.
# ---------------------------------------------------------------------------
SIGNAL_REEL_MAP = {
    "dominant_unit_demand": [39, 108],
    "rental_activity_growth": [11, 41, 42],
    "project_momentum": [1, 76, 93],
    "rent_growth_flat_price": [214, 216],
    "supply_demand_imbalance": [83, 84, 197, 220],
}
OPPORTUNITY_REEL_MAP = {
    "high_yield_high_demand": [36, 54],
    "rising_sales_momentum": [11, 13],
    "rental_growth_outpacing_price": [214, 216],
}


def _reel_stub(reel_id: int) -> dict | None:
    r = MANIFEST_BY_ID.get(reel_id)
    if not r:
        return None
    return {"id": r["id"], "title": r["title"], "category": r["category"], "status": r["status"]}


@router.get("/meta/opportunities")
def ready_to_make(period: str = "90d", limit: int = 12, con=Depends(db)):
    from apps.api.routers.opportunities import opportunities as _opportunities
    from apps.api.routers.signals import signals as _signals

    opp = _opportunities(period, con)
    sig = _signals(period, 5, con)

    cards = []
    for key, items in [
        ("high_yield_high_demand", opp["high_yield_high_demand"]),
        ("rising_sales_momentum", opp["rising_sales_momentum"]),
        ("rental_growth_outpacing_price", opp["rental_growth_outpacing_price"]),
    ]:
        for item in items[:3]:
            reels = [s for s in (_reel_stub(rid) for rid in OPPORTUNITY_REEL_MAP.get(key, [])) if s]
            cards.append({
                "finding": item["why"],
                "entity": item["community_name"],
                "communityKey": item["community_key"],
                "magnitude": item.get("estimated_gross_yield_pct") or item.get("change_pct") or item.get("rent_change_pct") or 0,
                "suggestedReels": reels,
            })

    for s in sig["signals"]:
        reels = [x for x in (_reel_stub(rid) for rid in SIGNAL_REEL_MAP.get(s["category"], [])) if x]
        name = s["evidence"].get("community") or s["evidence"].get("area") or s["evidence"].get("project")
        community_key = s["evidence"].get("community_key")
        cards.append({
            "finding": s["text"],
            "entity": name,
            "communityKey": community_key,
            "magnitude": abs(s["evidence"].get("change_pct") or s["evidence"].get("share_pct") or s["evidence"].get("ratio") or 0),
            "suggestedReels": reels,
        })

    cards = [c for c in cards if c["suggestedReels"]]
    cards.sort(key=lambda c: c["magnitude"], reverse=True)
    return {"period": period, "items": cards[:limit]}
