"""Area & project entity resolution: DLD raw names -> canonical warehouse
entities, optionally enriched with a link back to the scraper's SQLite data.

Design (see plan doc / docs/DATA_MODEL.md for the full rationale):
- DLD is the primary/canonical source for *which* areas and projects exist
  (267 official communities vs. the scraper's ~60; 2,957 DLD projects vs. 185
  scraped developments). Every distinct DLD area/project name becomes a
  first-class dimension row whether or not a scraped match is found.
- Matching never silently merges: exact match -> "exact", rapidfuzz score
  >=90 -> "fuzzy_high" (auto-linked), 75-89 -> "fuzzy_low" (score/candidate
  recorded but NOT auto-linked — surfaced for review), <75 -> "unmatched".
- A confirmed manual review is persisted in entity_alias_overrides and takes
  priority over automatic matching on every subsequent run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from ingestion.normalize import canonical_key

AUTO_LINK_THRESHOLD = 90
SUGGEST_THRESHOLD = 75

# A general "raw name's words are a subset of a longer candidate's words"
# auto-match heuristic was tried and reverted (see git history) — it
# correctly resolved clean cases like "BAY SQUARE" -> "Bay Square Building
# 1", but a manual audit of everything it newly matched also turned up
# real wrong merges purely from coincidental token overlap: "AL FURJAN"
# (a whole community's worth of DLD sales) landed on "Al Furjan Masjid" — a
# single mosque — for no reason other than being the shortest candidate
# containing both words, and "THE DUBAI MALL" landed on an unrelated hotel
# near Mall of the Emirates. That's exactly the silent-merge risk this
# module's design explicitly forbids. Cases like Bay Square are handled
# instead via a manually-reviewed entity_alias_overrides row (see
# scripts/seed_entity_overrides.py) rather than a blanket heuristic.

@dataclass
class MatchResult:
    matched_id: int | None
    confidence: str  # exact | fuzzy_high | fuzzy_low | unmatched
    score: float
    candidate_key: str | None  # the scraped-side key that was matched against


def _split_aliases(also_known_as: str | None) -> list[str]:
    if not also_known_as:
        return []
    parts = re.split(r"[,/;|]| and ", also_known_as)
    return [p.strip() for p in parts if p.strip()]


def match_name(
    raw_key: str,
    candidates: dict[str, int],
    overrides: dict[str, int] | None = None,
) -> MatchResult:
    """Match one canonicalized raw name against a {canonical_key: id} pool."""
    if overrides and raw_key in overrides:
        return MatchResult(overrides[raw_key], "exact", 100.0, raw_key)

    if not raw_key:
        return MatchResult(None, "unmatched", 0.0, None)

    if raw_key in candidates:
        return MatchResult(candidates[raw_key], "exact", 100.0, raw_key)

    if not candidates:
        return MatchResult(None, "unmatched", 0.0, None)

    best = process.extractOne(raw_key, candidates.keys(), scorer=fuzz.token_sort_ratio)
    if best is None:
        return MatchResult(None, "unmatched", 0.0, None)
    cand_key, score, _ = best
    if score >= AUTO_LINK_THRESHOLD:
        return MatchResult(candidates[cand_key], "fuzzy_high", score, cand_key)
    if score >= SUGGEST_THRESHOLD:
        return MatchResult(None, "fuzzy_low", score, cand_key)
    return MatchResult(None, "unmatched", score, None)


def build_area_candidates(scraped_areas: list[dict], scraped_sub_communities: list[dict]) -> dict[str, int]:
    """{canonical_key -> scraped areas.id} built from name, also_known_as
    aliases, and dld_community_name_en. Sub-communities resolve to their
    *parent* area id (DLD's AREA_EN grain is community-level, not sub-community).
    """
    candidates: dict[str, int] = {}
    for row in scraped_areas:
        area_id = row["id"]
        for raw in (row.get("name"), row.get("dld_community_name_en")):
            key = canonical_key(raw)
            if key:
                candidates.setdefault(key, area_id)
        for alias in _split_aliases(row.get("also_known_as")):
            key = canonical_key(alias)
            if key:
                candidates.setdefault(key, area_id)
    for row in scraped_sub_communities:
        key = canonical_key(row.get("name"))
        parent_id = row.get("parent_area_id")
        if key and parent_id is not None:
            candidates.setdefault(key, parent_id)
    return candidates


def build_project_candidates(
    scraped_developments: list[dict],
    scraped_buildings: list[dict],
) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
    """Returns (development_candidates, building_candidates).

    development_candidates: {canonical_key -> developments.id}
    building_candidates: {canonical_key -> (buildings.id, development_id)}
    """
    dev_candidates: dict[str, int] = {}
    for row in scraped_developments:
        key = canonical_key(row.get("name"))
        if key:
            dev_candidates.setdefault(key, row["id"])
    building_candidates: dict[str, tuple[int, int]] = {}
    for row in scraped_buildings:
        key = canonical_key(row.get("name"))
        if key:
            building_candidates.setdefault(key, (row["id"], row["development_id"]))
    return dev_candidates, building_candidates


def resolve_project(
    raw_key: str,
    dev_candidates: dict[str, int],
    building_candidates: dict[str, tuple[int, int]],
    overrides: dict[str, int] | None = None,
) -> tuple[MatchResult, int | None]:
    """Try building-level match first (finer grain, e.g. a specific tower),
    then fall back to development-level. Returns (MatchResult-for-dev-id,
    matched_building_id-or-None). MatchResult.matched_id is always a
    developments.id (or None) so callers get one consistent "which
    development does this roll up to" answer regardless of which grain matched.
    """
    building_keys = {k: dev_id for k, (bid, dev_id) in building_candidates.items()}
    b_match = match_name(raw_key, building_keys, overrides)
    if b_match.confidence in ("exact", "fuzzy_high") and b_match.candidate_key in building_candidates:
        bid, dev_id = building_candidates[b_match.candidate_key]
        return MatchResult(dev_id, b_match.confidence, b_match.score, b_match.candidate_key), bid

    d_match = match_name(raw_key, dev_candidates, overrides)
    return d_match, None
