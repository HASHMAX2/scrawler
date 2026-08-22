"""Ranks project/building search candidates for the autocomplete endpoint.

Tiered, deterministic-first ranking (lower tier number = better match):
  0. Exact master-project canonical match
  1. Exact building canonical match
  2. Manual alias override match
  3. Prefix match (candidate's canonical key starts with the query)
  4. Token-subset match (every query word appears in the candidate's key)
  5. Fuzzy match (rapidfuzz token_sort_ratio, must clear FUZZY_THRESHOLD)

Within equal tiers, a master project sorts ahead of its own buildings —
this is what makes "Azizi Venice" (exact match) list the master ahead of
"Azizi Venice 9" even though both are exact-ish hits, and is the literal
acceptance criterion from the product spec (§17).

Pure Python, no DB access — takes an already-fetched candidate list, so it's
directly unit-testable and fast enough (a few thousand short-string
comparisons) to run per-request without a separate cache layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 70


@dataclass(frozen=True)
class SearchCandidate:
    id: int
    kind: str  # 'master' | 'building'
    display_name: str
    canonical_key: str
    subtitle: str
    slug: str
    master_slug: str | None = None  # set for buildings; the parent's slug


@dataclass(frozen=True)
class RankedResult:
    candidate: SearchCandidate
    tier: int
    score: float


def rank_candidates(
    query_key: str,
    candidates: list[SearchCandidate],
    overrides: dict[str, str] | None = None,
) -> list[RankedResult]:
    """`query_key` must already be canonicalized (see ingestion.normalize.canonical_key).
    `overrides` maps a raw canonical key -> the canonical key of the entity it
    should resolve to (manual corrections), checked before automatic tiers.
    """
    overrides = overrides or {}
    query_tokens = set(query_key.split())
    results: list[RankedResult] = []

    for c in candidates:
        if query_key in overrides and overrides[query_key] == c.canonical_key:
            tier, score = 2, 100.0
        elif c.canonical_key == query_key:
            tier, score = (0 if c.kind == "master" else 1), 100.0
        elif query_key and c.canonical_key.startswith(query_key):
            tier, score = 3, 90.0
        elif query_tokens and query_tokens.issubset(set(c.canonical_key.split())):
            tier, score = 4, 80.0
        else:
            score = fuzz.token_sort_ratio(query_key, c.canonical_key)
            if score < FUZZY_THRESHOLD:
                continue
            tier = 5
        results.append(RankedResult(c, tier, score))

    results.sort(key=lambda r: (r.tier, 0 if r.candidate.kind == "master" else 1, -r.score, r.candidate.display_name))
    return results
