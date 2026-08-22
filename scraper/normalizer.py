"""Normalization helpers: status vocabulary, dates, integers/currency parsed from
Propsearch's free-text fields. Every normalizer keeps the raw source string alongside
its parsed value so nothing scraped is thrown away (brief §13).
"""
from __future__ import annotations

import re
from datetime import datetime

# Canonical status vocabulary from the brief (§5 Status). Raw badge/label text observed
# on Propsearch (see PROPSEARCH_STRUCTURE.md §6) maps onto this set. Unmatched raw text
# maps to "other" rather than being guessed at.
_STATUS_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"cancelled", re.I), "cancelled"),
    (re.compile(r"on[\s-]?hold", re.I), "on_hold"),
    (re.compile(r"delayed", re.I), "delayed"),
    (re.compile(r"complete", re.I), "completed"),
    (re.compile(r"under\s*development|under\s*construction|construction", re.I), "under_construction"),
    (re.compile(r"planned|planning|design\s*stage", re.I), "planned"),
    (re.compile(r"announced", re.I), "announced"),
]


def normalize_status(raw_status: str | None) -> str:
    """Map a raw Propsearch status label to the canonical vocabulary.

    Order matters: "Under development (Cancelled)" must match "cancelled" before the
    more general "under development" pattern, so cancelled/on-hold/delayed checks run
    first.
    """
    if not raw_status:
        return "other"
    text = raw_status.strip()
    if not text:
        return "other"
    for pattern, canonical in _STATUS_MAP:
        if pattern.search(text):
            return canonical
    return "other"


_INT_RE = re.compile(r"[\d,]+")


def parse_int(text: str | None) -> int | None:
    """Parse the first integer found in free text (commas allowed). Returns None if no
    digits are present — never coerces missing data to 0 (brief §6).
    """
    if not text:
        return None
    match = _INT_RE.search(text)
    if not match:
        return None
    digits = match.group(0).replace(",", "")
    if not digits:
        return None
    return int(digits)


_UNITS_TOTAL_RE = re.compile(r"total of\s+([\d,]+)\s+units", re.I)


def parse_total_units(text: str | None) -> tuple[int | None, str | None]:
    """Parse Propsearch's "The development contains a total of N units." sentence.

    Returns (value, raw_text). Value is None if the sentence/pattern isn't present —
    per the brief, missing unit data must stay UNKNOWN, never become 0.
    """
    if not text:
        return None, None
    match = _UNITS_TOTAL_RE.search(text)
    if match:
        return int(match.group(1).replace(",", "")), text.strip()
    return None, text.strip() if text.strip() else None


_MONTH_YEAR_RE = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b",
    re.I,
)
_YEAR_ONLY_RE = re.compile(r"\b(19|20)\d{2}\b")
_QUARTER_RE = re.compile(r"\bQ([1-4])\s+(\d{4})\b", re.I)

_MONTH_LOOKUP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_fuzzy_date(text: str | None) -> str | None:
    """Best-effort extraction of a date from free text, returned as an ISO-ish string.

    Handles three granularities actually observed on Propsearch:
      - "June 2015" -> "2015-06"
      - "Q1 2025" -> "2025-Q1"
      - a bare "2021" -> "2021"
    Returns None if nothing date-like is found. Does not guess a day-of-month since the
    source data is never that precise.
    """
    if not text:
        return None
    match = _MONTH_YEAR_RE.search(text)
    if match:
        month_key = match.group(1)[:3].lower()
        month_num = _MONTH_LOOKUP.get(month_key)
        year = match.group(2)
        if month_num:
            return f"{year}-{month_num:02d}"
    match = _QUARTER_RE.search(text)
    if match:
        return f"{match.group(2)}-Q{match.group(1)}"
    match = _YEAR_ONLY_RE.search(text)
    if match:
        return match.group(0)
    return None


_CURRENCY_RE = re.compile(r"AED\s*([\d,]+)", re.I)
_USD_RE = re.compile(r"USD\s*([\d.]+)\s*m", re.I)


def parse_project_value(text: str | None) -> tuple[float | None, float | None]:
    """Parse "AED 203,168,000 (USD 55.3m)" style project-value text -> (aed, usd)."""
    if not text:
        return None, None
    aed = None
    usd = None
    m = _CURRENCY_RE.search(text)
    if m:
        aed = float(m.group(1).replace(",", ""))
    m = _USD_RE.search(text)
    if m:
        usd = float(m.group(1)) * 1_000_000
    return aed, usd


_TXN_DATE_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4})")


def parse_transaction_date(text: str | None) -> str | None:
    """Parse "31 Jul 2026" / "31st Jul 2026" -> "2026-07-31"."""
    if not text:
        return None
    match = _TXN_DATE_RE.search(text)
    if not match:
        return None
    day, month_name, year = match.groups()
    month_num = _MONTH_LOOKUP.get(month_name[:3].lower())
    if not month_num:
        return None
    try:
        return datetime(int(year), month_num, int(day)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def parse_money(text: str | None) -> float | None:
    """Parse a plain "AED 1,100,000" style figure to a float."""
    if not text:
        return None
    m = _CURRENCY_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_size_sqft(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*sq\.?\s*ft", text, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def parse_coordinates(html: str) -> tuple[float | None, float | None]:
    """Extract lat,lng from the Google Maps Embed iframe `q=` param present on
    building/development pages (see PROPSEARCH_STRUCTURE.md).
    """
    match = re.search(r"maps/embed/v1/place\?[^\"'<>]*?q=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)", html)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


# Malls/landmarks share the exact same /dubai/{slug} URL template AND overview-prose
# template ("X is an area located within Y, Dubai.") as genuine residential
# communities — verified directly against the real scraped data, which is why this is
# NOT prose-pattern matching. `dld_community_code IS NULL` alone was tried and
# rejected: it also matches legitimate communities whose DLD linkage is simply
# missing in this dataset (e.g. "The Springs", "The Greens"), so misclassifying by
# that signal alone would wrongly relabel real communities as landmarks.
#
# "mall" is a safe, self-describing keyword match (verified: catches exactly the 6
# known mall rows in the real data, zero false positives against the other 46 names
# sharing a NULL dld_community_code). Beyond malls, the remaining non-residential
# names (attractions, a petrol station, supermarkets) don't share a common safe
# keyword — guessing a broader heuristic risks silently misclassifying an ambiguous
# real community (see the plan's "flag rather than silently merge" principle applied
# here to classification, not just entity-resolution). They're captured in a small,
# explicit, manually-verified list instead of an automatic rule; extend this set only
# after directly inspecting a candidate name, the same way this list was built.
_MALL_NAME_RE = re.compile(r"\bmall\b", re.IGNORECASE)

KNOWN_LANDMARK_AREA_NAMES: frozenset[str] = frozenset({
    "ski dubai", "skydive dubai", "madinat jumeirah complex", "the walk jbr",
    "dubai miracle garden", "grandiose supermarket sports city", "enoc station jvc",
    "sports city supermarket", "the springs souk", "the storm coaster",
})


_ALIAS_SPLIT_RE = re.compile(r"\s*(?:,|/|;|\band\b)\s*", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def split_aliases(raw: str | None) -> list[str]:
    """Splits a free-text also_known_as field (e.g. "JVC" today; potentially
    "JVC, Jumeirah Village Circle Dubai" for a richer future source) into
    individual alias strings. Empty/whitespace-only input yields an empty list,
    never a list containing an empty string.
    """
    if not raw or not raw.strip():
        return []
    parts = _ALIAS_SPLIT_RE.split(raw.strip())
    return [p.strip() for p in parts if p.strip()]


def normalize_alias(text: str) -> str:
    """Light normalization for alias dedup/matching: casefold + collapse
    whitespace. Deliberately simpler than a full canonical-key normalizer (no
    punctuation/accent stripping) — this only needs to catch exact-duplicate
    aliases within one source, not cross-source fuzzy matching.
    """
    return _WS_RE.sub(" ", text.strip().lower())


def classify_area_type(name: str | None) -> str:
    """Returns 'mall', 'landmark', or 'community' (the safe default for anything not
    positively identified as one of the other two).
    """
    if not name:
        return "community"
    key = name.strip().lower()
    if _MALL_NAME_RE.search(key):
        return "mall"
    if key in KNOWN_LANDMARK_AREA_NAMES:
        return "landmark"
    return "community"
