"""Data-availability classification for the Reel Master Library.

The manifest (apps/api/data/reel_manifest.json) tags each of the 235 reels
with the source codes the master document specifies (DLD-T, DLD-R, DLD-P,
Mollak, DDSE, ...). This module turns those tags into a real, inspectable
status against what this database ACTUALLY has today — never a guess.

Per the explicit product instruction: transaction (DLD-T) and rental (DLD-R)
data, plus our own derived project/developer/supply tables built from the
scraped Propsearch catalog (which the master doc's own source legend calls
"OWN" / "your transformed analytics" — a legitimate Tier 2 source, not a
downgrade), are the primary operational layer and must default reels to
READY whenever they're sufficient. Only genuinely absent sources (official
DLD project registry specifics, service charges, population/macro
statistics, infrastructure plans, live listings, multi-year history,
independent research) push a reel to partial or external.
"""
from __future__ import annotations

# Backed by real tables in this warehouse: fact_sales, fact_rentals,
# dim_project/dim_master_project (building + master-project grain), and the
# scraped.developments/buildings/unit_supply tables that stand in for DLD-P
# and DLD-U/B (Propsearch's own project/unit catalog, entity-resolved onto
# the DLD transaction data).
FULLY_AVAILABLE = {"DLD-T", "DLD-R", "OWN", "DLD-P", "DLD-U/B"}

# Sources that would enrich a reel but whose absence degrades one metric
# rather than making the whole analysis impossible — the reel still runs
# with a named gap instead of being blocked outright.
PARTIAL_ENRICHMENT = {"Mollak", "DEV", "KF", "Bayut", "PF", "LIST"}

# Sources this database has none of, and no real substitute for. A reel
# that fundamentally depends on one of these is honestly External, never
# faked from the transaction/rental data.
EXTERNAL_ONLY = {"DDSE", "2040/RTA", "Pulse", "DLD-V"}

SOURCE_LABELS = {
    "DLD-T": "DLD Transactions",
    "DLD-R": "DLD Rent Contracts",
    "DLD-P": "Project/Developer Catalog (scraped, entity-resolved)",
    "DLD-U/B": "Units & Buildings (scraped)",
    "DLD-V": "DLD Valuations",
    "OWN": "Our Transaction + Rental + Project Database",
    "Pulse": "Dubai Pulse (historical, multi-year)",
    "PF": "Property Finder",
    "Bayut": "Bayut",
    "KF": "Knight Frank / REIDIN",
    "DDSE": "Dubai Statistics / DDSE",
    "2040/RTA": "Dubai 2040 + RTA Infrastructure",
    "DEV": "Developer Material (brochures, payment plans)",
    "Mollak": "Mollak Service Charges",
    "LIST": "Live Asking Listings",
}


def classify_sources(sources: list[str]) -> tuple[str, list[str]]:
    """Returns (status, missing) where status is one of
    "ready" | "partial" | "external" and missing lists the specific source
    codes this database cannot supply for that reel.
    """
    external_missing = [s for s in sources if s in EXTERNAL_ONLY]
    if external_missing:
        return "external", external_missing
    partial_missing = [s for s in sources if s in PARTIAL_ENRICHMENT]
    if partial_missing:
        return "partial", partial_missing
    return "ready", []


# One resolver type per manifest category — the reusable analytics engine
# a reel in that category is executed against (apps/api/analytics/reel_resolvers.py).
# Many reels within a category share the exact same resolver, parameterized
# differently by the workspace UI, per the "one dataset, many reels" rule.
CATEGORY_RESOLVER = {
    "Weekly / Monthly Market Reels": "market_snapshot",
    "Community vs Community": "community_comparison",
    "Rental & Yield Reels": "yield_ranking",
    "Off-Plan Project Analysis": "project_scorecard",
    "Supply / Oversupply": "supply_analysis",
    "Developer Reels": "developer_ranking",
    "Price per Square Foot Content": "psf_ranking",
    "Liquidity / Exit Reels": "liquidity_ranking",
    "Budget-Based Reels": "budget_explorer",
    "Population / Demand / Macro Reels": "macro",
    '"Is This Project Overpriced?" Repeatable Series': "project_scorecard",
    '"What Would I Buy?" Series': "budget_explorer",
    "Myth-Busting Reels": "myth_test",
    '"The Data Nobody Shows You" Series': "building_insight",
    "Supplementary Ideas": "market_snapshot",
}

# A handful of supplementary ideas (no numbered category) read more
# naturally against a different resolver than the category default.
SUPPLEMENTARY_RESOLVER_OVERRIDES = {
    230: "yield_ranking",       # Are advertised rental yields actually real?
    234: "budget_explorer",     # What can AED 1M/2M/3M actually buy today
    235: "project_scorecard",   # Is this project's AED X PSF expensive?
}

FRANCHISES = {
    "Dubai This Week": {
        "description": "Weekly market pulse — top projects, developers, communities, value, volume, off-plan share and one unusual movement.",
        "ranges": [range(1, 16)],
    },
    "Would I Buy It?": {
        "description": "Project underwriting — one launch/project run through the same PSF, rent, supply, liquidity, developer and payment-plan scorecard.",
        "ranges": [range(56, 81), range(166, 178)],
    },
    "Dubai Data Battle": {
        "description": "Community vs community — two areas, a handful of metrics, one verdict tied to a specific investor objective.",
        "ranges": [range(16, 36)],
    },
    "Where Would I Put AED X?": {
        "description": "Budget and goal-based investing — budget first, then realistic options ranked on actual sale/rent data.",
        "ranges": [range(136, 151), range(178, 193)],
    },
    "The Data Nobody Shows You": {
        "description": "Proprietary analysis — building-level rent, transaction velocity, supply ratios, asking-vs-sale gaps and outliers.",
        "ranges": [range(208, 228)],
    },
    "Dubai Myth vs Data": {
        "description": "Take a common Dubai property claim and test it against one decisive dataset and one important caveat.",
        "ranges": [range(193, 208)],
    },
}


def franchise_for_id(reel_id: int) -> str | None:
    for name, spec in FRANCHISES.items():
        for r in spec["ranges"]:
            if reel_id in r:
                return name
    return None


def resolver_for(reel: dict) -> str:
    override = SUPPLEMENTARY_RESOLVER_OVERRIDES.get(reel["id"])
    if override:
        return override
    return CATEGORY_RESOLVER.get(reel["category"], "market_snapshot")
