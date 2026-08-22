"""URL canonicalization and allowlist rules for the Propsearch crawler.

Only the URL shapes actually observed and documented in PROPSEARCH_STRUCTURE.md are
allowed. See that file for how each shape was confirmed.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

ALLOWED_HOST = "propsearch.ae"

# Path prefixes worth crawling. Everything else (blog, FAQ, account pages, pro-tools,
# static assets, live listing search pages, etc.) is out of scope.
#
# Developer/contractor profile pages (/dubai-property-developers/*,
# /dubai-construction-companies/*) are deliberately NOT in the crawl frontier: a
# developer like Nakheel has projects across the whole of Dubai, so following links
# from its profile page would blow an area-scoped crawl (e.g. seeding with just
# Jumeirah Village Circle) out into unrelated areas — see PROPSEARCH_STRUCTURE.md §7/§8.
# Developer name+URL is still captured as data (from the free-text "The developer"
# field on each development page), just never used as a crawl seed.
ALLOWED_PATH_PREFIXES = (
    "/dubai/",
)

# Sub-paths under /dubai/{slug}/ that are legitimate crawl targets (area supporting pages).
AREA_SUBPAGE_SUFFIXES = (
    "/buildings",
    "/amenities",
    "/schools",
    "/things-to-do",
)

# Never crawl these even though they share a prefix with allowed paths — live listing
# search / paid tools / account surfaces, out of scope per the brief.
EXCLUDED_SUBSTRINGS = (
    "/properties-buy-rent",
    "/pro-tools",
    "/account/",
    "propsearch-pro-subscription",
)

# File extensions that indicate a static asset, not an HTML page.
_ASSET_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".css", ".js",
    ".ico", ".woff", ".woff2", ".ttf", ".mp4",
)


def canonicalize(url: str, base: str | None = None) -> str:
    """Normalize a URL for dedup/visited-tracking purposes.

    - Resolves relative URLs against `base`.
    - Forces https scheme and lowercase host.
    - Strips the fragment.
    - Drops query params that are not the pagination `page` param (tracking/marketing
      params observed elsewhere on the site are not part of the documented structure).
    - Strips a trailing slash (except for the bare root).
    """
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    scheme = "https"
    netloc = parts.netloc.lower()
    path = parts.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept_qs = [(k, v) for k, v in parse_qsl(parts.query) if k == "page"]
    query = urlencode(sorted(kept_qs))
    return urlunsplit((scheme, netloc, path, query, ""))


def is_allowed(url: str) -> bool:
    """URL allowlist: same-host, allowed path prefix, not an excluded/asset URL."""
    parts = urlsplit(url)
    if parts.netloc and parts.netloc.lower() != ALLOWED_HOST:
        return False
    path = parts.path
    if path.lower().endswith(_ASSET_EXTENSIONS):
        return False
    if any(sub in path for sub in EXCLUDED_SUBSTRINGS):
        return False
    if path == "/dubai" or path == "/dubai/":
        # Bare /dubai has been observed to 404; the real Dubai landing content lives at "/".
        return False
    return any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES)


def slug_from_dubai_url(url: str) -> str | None:
    """Extract the {slug} from https://propsearch.ae/dubai/{slug}[/subpage].

    Returns None for URLs that are not a plain /dubai/{slug}[...] shape (e.g. the
    /dubai/area-guides index itself, which is not an area/development record).
    """
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2 or segments[0] != "dubai":
        return None
    slug = segments[1]
    if slug == "area-guides":
        return None
    return slug


def area_subpage_kind(url: str) -> str | None:
    """If `url` is an area supporting sub-page (/dubai/{slug}/buildings etc), return the
    suffix name (e.g. "buildings"); otherwise None.
    """
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) == 3 and segments[0] == "dubai":
        suffix = "/" + segments[2]
        if suffix in AREA_SUBPAGE_SUFFIXES:
            return segments[2]
    return None


def is_area_guides_index(url: str) -> bool:
    parts = urlsplit(url)
    return parts.path.rstrip("/") == "/dubai/area-guides"


@dataclass(frozen=True)
class PageRef:
    url: str
    depth: int
    discovered_from: str | None = None
