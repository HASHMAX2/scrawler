"""Regression coverage for the crawl-scoping bug found during manual testing: an area
page's own prose (e.g. "21 minutes to Dubai Mall" in Transport & Access) links to
unrelated areas, and naively following every link on the page turned a crawl seeded
with one specific area into a crawl of most of Dubai. See discovery.py's Crawler
docstring/comments for the fix (a `trusted_area_urls` set that only grows via a
parsed area's explicit `subcommunities`, never via blanket link-scraping).
"""
from __future__ import annotations

from pathlib import Path

from scraper.discovery import Crawler
from scraper.fetcher import FetchResult
from scraper.storage import Store


def _area_html(title: str, breadcrumb_href: str, breadcrumb_text: str, body_links: str) -> str:
    return f"""
    <html><body><main>
      <a href="https://propsearch.ae">Propsearch</a>
      <a href="{breadcrumb_href}">{breadcrumb_text}</a>
      <a href="https://propsearch.ae/dubai/seed-area">{title} Guide</a>
      <h1>{title}</h1>
      {body_links}
    </main></body></html>
    """


SEED_HTML = _area_html(
    "Seed Area", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links="""
      <h2>Sub-communities</h2>
      <div>There are 1 sub-communities in Seed Area. Learn more in the following guides.</div>
      <a href="https://propsearch.ae/dubai/seed-child" class="group">
        <div class="font-bold">Seed Child</div>
        <span class="material-icons">check_circle</span>Complete
      </a>
      <p>It takes 20 minutes to drive to <a href="https://propsearch.ae/dubai/faraway-area">Faraway Area</a>.</p>
    """,
)

CHILD_HTML = _area_html(
    "Seed Child", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links="<p>A child area with no further links.</p>",
)

# A tangentially-linked area with its OWN sub-community — if trust ever leaked, this
# child would end up in trusted_area_urls too.
FARAWAY_HTML = _area_html(
    "Faraway Area", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links="""
      <h2>Sub-communities</h2>
      <a href="https://propsearch.ae/dubai/faraway-child" class="group">
        <div class="font-bold">Faraway Child</div>
        <span class="material-icons">check_circle</span>Complete
      </a>
    """,
)

FARAWAY_CHILD_HTML = _area_html(
    "Faraway Child", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links="<p>Should never be fetched in a scoped crawl.</p>",
)

PAGES = {
    "https://propsearch.ae/dubai/seed-area": SEED_HTML,
    "https://propsearch.ae/dubai/seed-child": CHILD_HTML,
    "https://propsearch.ae/dubai/faraway-area": FARAWAY_HTML,
    "https://propsearch.ae/dubai/faraway-child": FARAWAY_CHILD_HTML,
}


class FakeFetcher:
    """Serves canned HTML instead of hitting the network; mirrors the Fetcher.fetch
    interface the Crawler depends on."""
    consecutive_blocks = 0

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.fetched: list[str] = []

    def fetch(self, url: str) -> FetchResult:
        self.fetched.append(url)
        html = self.pages.get(url)
        if html is None:
            return FetchResult(url=url, final_url=url, status_code=404, html=None, error="not_found")
        return FetchResult(url=url, final_url=url, status_code=200, html=html, error=None)


def test_scoped_crawl_does_not_expand_tangentially_linked_areas(tmp_path):
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(PAGES)
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20)

    crawler.run("https://propsearch.ae/dubai/seed-area")

    # The seed and its true child must be crawled and stored.
    areas = {r["url"] for r in store.conn.execute("SELECT url FROM areas").fetchall()}
    assert "https://propsearch.ae/dubai/seed-area" in areas
    assert "https://propsearch.ae/dubai/seed-child" in areas

    # Faraway Area gets fetched once (its own data is harmless to keep)...
    assert "https://propsearch.ae/dubai/faraway-area" in fetcher.fetched
    # ...but its child must NEVER be fetched — that would mean trust leaked/cascaded.
    assert "https://propsearch.ae/dubai/faraway-child" not in fetcher.fetched

    store.close()


def test_full_dubai_mode_expands_everything(tmp_path):
    """Seeding with the area-guides index itself is the one case where following
    every discovered area is correct — the user explicitly asked for all of Dubai."""
    pages = dict(PAGES)
    pages["https://propsearch.ae/dubai/area-guides"] = _area_html(
        "Area Guides Index", "https://propsearch.ae/dubai/area-guides", "Area Guides",
        body_links='<a href="https://propsearch.ae/dubai/faraway-area">Faraway Area</a>',
    )
    store = Store(tmp_path / "test2.db")
    fetcher = FakeFetcher(pages)
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20)

    crawler.run("https://propsearch.ae/dubai/area-guides")

    assert "https://propsearch.ae/dubai/faraway-area" in fetcher.fetched
    assert "https://propsearch.ae/dubai/faraway-child" in fetcher.fetched
    store.close()


# -- discover / enrich modes -------------------------------------------------

def _buildings_listing_html(cards: list[tuple[str, str, str]]) -> str:
    """cards: list of (name, url, status_text). Mirrors the real DOM shape
    parser.parse_building_cards expects (verified against tests/fixtures/
    area_buildings_listing.html): a `.line-clamp-2.font-bold` name div inside an
    `<a title=...>`, followed by a SIBLING <div> containing a <span> icon then the
    status text as the icon's next sibling text node.
    """
    card_html = "".join(
        f"""
        <a href="{url}" title="{name}"><div class="line-clamp-2 font-bold">{name}</div></a>
        <div><span class="material-icons">check_circle</span>{status}</div>
        """
        for name, url, status in cards
    )
    return f"""
    <html><body><main>
      <a href="https://propsearch.ae/dubai/area-guides">Area Guides</a>
      <a href="https://propsearch.ae/dubai/building-guides">Building Guides</a>
      {card_html}
    </main></body></html>
    """


DISCOVER_SEED_HTML = _area_html(
    "Discover Area", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links='<a href="https://propsearch.ae/dubai/discover-area/buildings">See all buildings</a>',
)


def _minimal_development_html(name: str) -> str:
    # classify_page() identifies a development page via its breadcrumb link
    # ("Propsearch > Building Guides > {Name} Guide") — without it the page
    # classifies as "unknown" and never reaches upsert_development.
    return f"""
    <html><body><main>
      <a href="https://propsearch.ae/dubai/buildings">Building Guides</a>
      <h1>{name}</h1>
      <p>A development.</p>
    </main></body></html>
    """


def test_discover_mode_creates_stubs_without_fetching_development_pages(tmp_path):
    pages = {
        "https://propsearch.ae/dubai/discover-area": DISCOVER_SEED_HTML,
        "https://propsearch.ae/dubai/discover-area/buildings": _buildings_listing_html([
            ("Tower A", "https://propsearch.ae/dubai/tower-a", "Complete"),
            ("Tower B", "https://propsearch.ae/dubai/tower-b", "Under construction"),
        ]),
    }
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(pages)
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20, mode="discover")

    crawler.run("https://propsearch.ae/dubai/discover-area")

    # The buildings-listing page itself IS fetched (that's how stubs get created)...
    assert "https://propsearch.ae/dubai/discover-area/buildings" in fetcher.fetched
    # ...but the individual development pages must NOT be — that's the whole point
    # of discover mode being cheaper than a full crawl.
    assert "https://propsearch.ae/dubai/tower-a" not in fetcher.fetched
    assert "https://propsearch.ae/dubai/tower-b" not in fetcher.fetched

    stubs = store.conn.execute("SELECT name, is_stub, normalized_status FROM developments ORDER BY name").fetchall()
    assert [dict(r) for r in stubs] == [
        {"name": "Tower A", "is_stub": 1, "normalized_status": "completed"},
        {"name": "Tower B", "is_stub": 1, "normalized_status": "under_construction"},
    ]
    store.close()


def test_enrich_mode_visits_stubs_and_clears_stub_flag(tmp_path):
    pages = {
        "https://propsearch.ae/dubai/discover-area": DISCOVER_SEED_HTML,
        "https://propsearch.ae/dubai/discover-area/buildings": _buildings_listing_html([
            ("Tower A", "https://propsearch.ae/dubai/tower-a", "Complete"),
        ]),
        "https://propsearch.ae/dubai/tower-a": _minimal_development_html("Tower A Full Detail"),
    }
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(pages)
    discover_crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20, mode="discover")
    discover_crawler.run("https://propsearch.ae/dubai/discover-area")
    assert store.conn.execute("SELECT COUNT(*) c FROM developments WHERE is_stub=1").fetchone()["c"] == 1

    enrich_crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20, mode="enrich")
    job_id = enrich_crawler.run_enrich()
    assert job_id is not None
    assert "https://propsearch.ae/dubai/tower-a" in fetcher.fetched

    row = store.conn.execute("SELECT is_stub, name, enriched_at FROM developments WHERE url=?",
                              ("https://propsearch.ae/dubai/tower-a",)).fetchone()
    assert row["is_stub"] == 0
    assert row["name"] == "Tower A Full Detail"
    assert row["enriched_at"] is not None
    store.close()


def test_run_enrich_with_no_stubs_returns_none(tmp_path):
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher({})
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw")
    assert crawler.run_enrich() is None
    store.close()


# -- mentioned_places wiring --------------------------------------------------

MENTIONS_SEED_HTML = _area_html(
    "Mentions Area", "https://propsearch.ae/dubai/area-guides", "Area Guides",
    body_links="""
      <div class="ps-3-col-block"><div class="ps-3-col-centre">
        <h2 class="ps-crosshead">Transport &amp; Access</h2>
      </div></div>
      <div class="ps-3-col-block"><div class="ps-3-col-centre ps-prose">
        <div class="ps-h3">Road access</div>
        <p>20 minutes to <a href="https://propsearch.ae/dubai/dubai-mall">Dubai Mall</a>.</p>
      </div></div>
    """,
)


def test_area_crawl_stores_mentioned_places(tmp_path):
    pages = {"https://propsearch.ae/dubai/mentions-area": MENTIONS_SEED_HTML}
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(pages)
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=5)

    crawler.run("https://propsearch.ae/dubai/mentions-area")

    rows = store.conn.execute(
        "SELECT name, linked_url, section, source_area_id, source_development_id "
        "FROM mentioned_places"
    ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Dubai Mall"
    assert row["linked_url"] == "https://propsearch.ae/dubai/dubai-mall"
    assert row["section"] == "Road access"
    assert row["source_area_id"] is not None
    assert row["source_development_id"] is None
    store.close()


def test_area_crawl_mentioned_places_upsert_does_not_duplicate_on_recrawl(tmp_path):
    pages = {"https://propsearch.ae/dubai/mentions-area": MENTIONS_SEED_HTML}
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(pages)
    Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=5).run(
        "https://propsearch.ae/dubai/mentions-area"
    )
    # Re-crawl the same seed (a second job) — must update the existing row, not
    # insert a duplicate (regression test for NULL-unsafe UNIQUE constraint matching).
    Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=5).run(
        "https://propsearch.ae/dubai/mentions-area"
    )
    count = store.conn.execute("SELECT COUNT(*) c FROM mentioned_places").fetchone()["c"]
    assert count == 1
    store.close()


def test_daily_budget_stops_crawl_gracefully(tmp_path):
    store = Store(tmp_path / "test.db")
    fetcher = FakeFetcher(PAGES)
    crawler = Crawler(store, fetcher, raw_dir=Path(tmp_path) / "raw", max_pages=20, max_requests_per_day=1)

    crawler.run("https://propsearch.ae/dubai/seed-area")

    # Budget of 1 means only the seed page gets processed this run, even though
    # more pages remain queued (its own child links were discovered and enqueued).
    assert len(fetcher.fetched) == 1
    assert store.requests_used_today() == 1
    counts = store.queue_counts(1)
    assert counts.get("pending", 0) > 0  # rest is still queued, resumable
    store.close()
