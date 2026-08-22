"""Deterministic (non-fuzzy) project -> building hierarchy extraction.

Given a raw DLD project name (already effectively building-grain, e.g.
"AZIZI VENICE 14"), derives:
  - a master-project canonical key ("azizi venice") that siblings share
  - a building label ("14") identifying this specific tower within the family
  - the extraction method used, so callers can grade confidence

This is intentionally rule-based, not fuzzy: merging two distinct dim_project
rows into one master project is a structural decision that must be
defensible (see docs/DATA_MODEL.md) — an unrelated project that merely
contains a shared word must never be silently merged. Fuzzy matching belongs
only at *search* time (ranking what a user might mean), never here.

Two patterns are recognized, tried in order:
  1. trailing_number: "<master> [tower|bldg|building|block|ph|phase] <N>"
     e.g. "AZIZI VENICE 14", "Boulevard Park 1", "Azizi Venice Tower 15"
  2. hyphen_split: "<master> - <building label>" (first hyphen only)
     e.g. "Creek Beach - Canopy - Moor" -> master "creek beach",
     building "Canopy - Moor"; "Remraam - Al Ramth" -> master "remraam"
Anything matching neither pattern is its own single-building master
("none") — a name with no detected siblings is still a perfectly valid
master project of one building, not a defect.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ingestion.normalize import canonical_key

_FILLER_WORDS = r"tower|bldg|building|block|ph|phase"
_TRAILING_NUMBER_RE = re.compile(rf"^(?P<master>.+?)\s+(?:(?:{_FILLER_WORDS})\s+)?(?P<num>\d{{1,4}})$")
_HYPHEN_SEPARATORS = (" - ", " – ", " — ")

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class HierarchyResult:
    master_key: str
    building_label: str | None
    method: str  # 'trailing_number' | 'hyphen_split' | 'none'


def extract_building_suffix(raw_name: str | None) -> HierarchyResult:
    key = canonical_key(raw_name)
    if not key:
        return HierarchyResult("", None, "none")

    m = _TRAILING_NUMBER_RE.match(key)
    if m:
        master = m.group("master").strip()
        if master:
            return HierarchyResult(master, m.group("num"), "trailing_number")

    if raw_name:
        # Only look for a separator before any parenthetical aside — a hyphen
        # inside "(Lavender - Gardenia - Rose)" is an enumeration, not a
        # master/building split, and must not be treated as one.
        paren_idx = raw_name.find("(")
        search_region = raw_name if paren_idx == -1 else raw_name[:paren_idx]
        for sep in _HYPHEN_SEPARATORS:
            if sep in search_region:
                prefix, suffix = raw_name.split(sep, 1)
                master_key = canonical_key(prefix)
                building_label = suffix.strip().rstrip(")").strip()
                if master_key and building_label:
                    return HierarchyResult(master_key, building_label, "hyphen_split")

    return HierarchyResult(key, None, "none")


def slugify(text: str) -> str:
    """URL-safe slug: lowercase, non-alphanumeric runs collapsed to a single
    hyphen, no leading/trailing hyphen. Assumes `text` is already reasonably
    normalized (e.g. output of canonical_key) but tolerates raw input too.
    """
    lowered = text.strip().lower()
    slug = _SLUG_STRIP_RE.sub("-", lowered).strip("-")
    return slug or "project"


def display_name_from_key(master_key: str) -> str:
    """Best-effort title-case for a purely-derived (virtual) master project
    name, e.g. "azizi venice" -> "Azizi Venice". Used only when no single
    raw source string cleanly represents the whole family.
    """
    return " ".join(word.capitalize() for word in master_key.split())
