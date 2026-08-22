"""Deterministic normalization rules for DLD sales/rental data.

Every mapping here is derived from the actual distinct values observed in the
source files (see docs/DATA_MODEL.md), not guessed. Anything not covered by an
explicit rule falls through to "Other"/"Unknown" rather than being silently
misclassified.
"""
from __future__ import annotations

import re
import unicodedata

CANONICAL_BEDROOMS = ["Studio", "1BR", "2BR", "3BR", "4BR", "5BR+", "Other", "Unknown"]

CANONICAL_PROPERTY_TYPES = [
    "Apartment", "Villa", "Townhouse", "Office", "Retail",
    "Hotel", "Industrial", "Land", "Other",
]

# PROP_SB_TYPE_EN (sales) / PROP_SUB_TYPE_EN (rentals) -> canonical_property_type.
# Keys are matched case-insensitively after strip().
_PROPERTY_TYPE_MAP: dict[str, str] = {
    "flat": "Apartment",
    "residential flats": "Apartment",
    "residential": "Apartment",
    "unit": "Apartment",
    "studio": "Apartment",
    "penthouse": "Apartment",
    "villa": "Villa",
    "complex villas": "Villa",
    "residential / residential villa": "Villa",
    "residential / villas": "Villa",
    "residential / attached villas": "Villa",
    "arabian house": "Villa",
    "stacked townhouses": "Townhouse",
    "office": "Office",
    "offices": "Office",
    "desk": "Office",
    "mezzanine": "Office",
    "commercial / offices / residential": "Office",
    "shop": "Retail",
    "shops": "Retail",
    "showroom": "Retail",
    "kiosk": "Retail",
    "store": "Retail",
    "supermarket": "Retail",
    "shopping mall": "Retail",
    "commercial": "Retail",
    "hotel": "Hotel",
    "hotel apartment": "Hotel",
    "hotel apartments": "Hotel",
    "hotel rooms": "Hotel",
    "hotel building": "Hotel",
    "warehouse": "Industrial",
    "warehouse complex": "Industrial",
    "complex warehouse": "Industrial",
    "workshop": "Industrial",
    "factory": "Industrial",
    "industrial": "Industrial",
    "labor camps": "Industrial",
    "labor camp": "Industrial",
    "staff accommodation": "Industrial",
    "land": "Land",
    "open land": "Land",
    "open space": "Land",
    "land parking": "Land",
    "general use": "Other",
    "building": "Other",
    "government housing": "Other",
    "school": "Other",
    "college": "Other",
    "nursery": "Other",
    "clinic": "Other",
    "medical center": "Other",
    "health club": "Other",
    "gym": "Other",
    "sports club": "Other",
    "bank": "Other",
    "petrol station": "Other",
    "exhbition center": "Other",
    "hospital": "Other",
    "ladies saloon": "Other",
    "parking": "Other",
    "sized partition": "Other",
    "restaurant": "Retail",
    "spa": "Other",
}

# ROOMS_EN (sales) direct labels that are not bedroom counts.
_NON_BEDROOM_ROOM_LABELS = {"hotel", "office", "shop"}


def canonical_property_type(prop_sub_type: str | None, prop_type: str | None = None) -> str:
    """Map a raw PROP_SB_TYPE_EN / PROP_SUB_TYPE_EN value to a canonical category.

    Falls back to `prop_type` (PROP_TYPE_EN, e.g. "Villa"/"Land") when the
    sub-type is missing or unrecognized, then to "Other" — never guesses.
    """
    for raw in (prop_sub_type, prop_type):
        if raw is None:
            continue
        key = str(raw).strip().lower()
        if key in _PROPERTY_TYPE_MAP:
            return _PROPERTY_TYPE_MAP[key]
    return "Other"


def canonical_bedroom_from_rooms_en(rooms_en: str | None) -> str | None:
    """Sales-side: parse DLD's `ROOMS_EN` (e.g. "1 B/R", "Studio", "PENTHOUSE").

    Returns None (not "Unknown") when the field is null, so callers can tell
    "field absent" apart from "field present but not a bedroom count".
    """
    if rooms_en is None or str(rooms_en).strip() == "":
        return None
    text = str(rooms_en).strip().lower()
    if text == "studio":
        return "Studio"
    if text in _NON_BEDROOM_ROOM_LABELS or text == "penthouse":
        return "Other"
    m = re.match(r"^(\d+)\s*b/?r$", text)
    if m:
        n = int(m.group(1))
        return f"{n}BR" if n <= 4 else "5BR+"
    return "Other"


def canonical_bedroom_from_rentals(rooms: float | None, prop_sub_type: str | None, prop_type: str | None) -> str:
    """Rental-side: `ROOMS` is numeric and populated almost exclusively for
    Villas; apartments/units carry no bedroom count in this dataset. Returns
    "Unknown" (not None) for the majority-null apartment case so downstream
    aggregation always has an explicit bucket rather than silently dropping
    rows from a group-by.
    """
    sub = (str(prop_sub_type).strip().lower() if prop_sub_type else "")
    if sub == "studio":
        return "Studio"
    if rooms is not None and not (isinstance(rooms, float) and rooms != rooms):  # not NaN
        n = int(rooms)
        if n <= 0:
            return "Studio"
        return f"{n}BR" if n <= 4 else "5BR+"
    return "Unknown"


_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def canonical_key(name: str | None) -> str:
    """Light-touch name canonicalization for matching: casefold, strip accents
    and punctuation, collapse whitespace. Deliberately does NOT strip tokens
    like "tower"/"phase"/numbers — that kind of aggressive stripping risks
    merging a master development with one of its distinct towers, which the
    entity-resolution design explicitly forbids doing silently.
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.strip().lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def parse_dld_date(value: str | None) -> str | None:
    """DLD dates arrive as ISO-ish "YYYY-MM-DD HH:MM:SS" strings; return just
    the date part in ISO form, or None if unparseable.
    """
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return m.group(1) if m else None
