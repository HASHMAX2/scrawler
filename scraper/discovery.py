"""Crawl orchestration: seeds a queue from one URL, fetches/classifies/parses/stores
each page, and enqueues newly-discovered allowed links. Checkpointed in SQLite so a
crashed crawl resumes from `crawl_queue` rather than restarting (brief §17).
"""
from __future__ import annotations

import logging
from pathlib import Path

from bs4 import BeautifulSoup

from scraper import parser
from scraper.fetcher import Fetcher
from scraper.storage import Store
from scraper.url_utils import area_subpage_kind, canonicalize, is_allowed, is_area_guides_index

logger = logging.getLogger("propsearch.discovery")

MAX_CONSECUTIVE_BLOCKS = 5


class Crawler:
    def __init__(self, store: Store, fetcher: Fetcher, raw_dir: Path, max_pages: int | None = None,
                 mode: str = "full", max_requests_per_day: int | None = None):
        """`mode`:
          - "full" (default): today's behavior — discover hierarchy and fully
            extract each page in one pass. Unchanged so existing scripts/muscle
            memory keep working.
          - "discover": breadth-first only. A /buildings listing page creates
            lightweight stub development rows directly from its cards (name/url/
            status) instead of enqueuing each development's own page — see
            Store.upsert_development_stub. Much cheaper: skips fetching every
            individual development page during this pass.
          - "enrich"/"update": not driven by run(); see run_enrich()/run_update().
        """
        self.store = store
        self.fetcher = fetcher
        self.raw_dir = raw_dir
        self.max_pages = max_pages
        self.mode = mode
        self.max_requests_per_day = max_requests_per_day
        self.full_dubai_mode = False
        # URLs it's legitimate to expand an AREA page's links from: the seed itself,
        # plus any URL explicitly named as a sub-community by an already-trusted area's
        # own page (see _process_one). Area pages are full of *content* links to
        # unrelated areas — "21 minutes to Dubai Mall", "16 minutes to Palm Jumeirah" in
        # the Transport & Access text, for instance — that are not part of the seeded
        # area's hierarchy at all. Fetching one such page is harmless (its own data is
        # still worth having), but treating it as a fresh expansion source is what
        # turned a "just Jumeirah Village Circle" crawl into all of Dubai Marina and
        # Palm Jumeirah during testing. Development pages don't get this treatment —
        # their outgoing links (master/sub-building, developer, area subpages) are all
        # legitimately part of the seeded hierarchy and safe to follow unconditionally.
        self.trusted_area_urls: set[str] = set()

    def run(self, seed_url: str) -> int:
        seed_url = canonicalize(seed_url)
        # A seed that IS the Dubai-wide area directory means "crawl all of Dubai" —
        # otherwise (a specific area/development URL) every page's breadcrumb links
        # back to that same directory, and blindly following it would explode a
        # deliberately scoped crawl (e.g. "just Jumeirah Village Circle") out into
        # all ~100+ Dubai areas. See PROPSEARCH_STRUCTURE.md / IMPLEMENTATION_STATUS.md.
        self.full_dubai_mode = is_area_guides_index(seed_url)
        self.trusted_area_urls.add(seed_url)
        job_id = self._get_or_create_job(seed_url)
        self.store.enqueue(job_id, seed_url, depth=0, discovered_from=None)
        return self._run_queue(job_id)

    def run_enrich(self, limit: int | None = None) -> int | None:
        """Mode 2 (brief §4): visit every stub development created by a prior
        `--mode discover` pass and extract its full detail fields. Returns None if
        there was nothing to enrich.
        """
        stub_rows = self.store.stub_development_urls(limit)
        if not stub_rows:
            logger.info("[ENRICH] No stub developments to enrich")
            return None
        job_id = self.store.create_job(f"enrich:{len(stub_rows)}-stubs")
        logger.info("[START] Enrichment job %d: %d stub developments queued", job_id, len(stub_rows))
        for row in stub_rows:
            self.store.enqueue(job_id, row["url"], depth=0, discovered_from=None)
        return self._run_queue(job_id)

    def run_update(self, limit: int | None = None) -> int | None:
        """Mode 3 (brief §4): re-check already-enriched developments most likely to
        have changed, instead of a full re-crawl. Returns None if there was nothing
        to check.
        """
        rows = self.store.update_candidates(limit)
        if not rows:
            logger.info("[UPDATE] No existing developments to check")
            return None
        job_id = self.store.create_job(f"update:{len(rows)}-candidates")
        logger.info("[START] Update job %d: %d candidates queued (priority: under-construction/planned first)", job_id, len(rows))
        for row in rows:
            self.store.enqueue(job_id, row["url"], depth=0, discovered_from=None)
        return self._run_queue(job_id)

    def _run_queue(self, job_id: int) -> int:
        processed = 0
        while True:
            if self.max_pages is not None and processed >= self.max_pages:
                logger.info("[LIMIT] Reached max_pages=%d, stopping this run", self.max_pages)
                break
            if self.max_requests_per_day is not None and self.store.requests_used_today() >= self.max_requests_per_day:
                logger.warning("[BUDGET] Daily request budget (%d) reached — stopping for today; "
                                "re-run the same command tomorrow to resume (checkpointed)", self.max_requests_per_day)
                break
            row = self.store.next_pending(job_id)
            if row is None:
                break
            self._process_one(job_id, row)
            processed += 1
            if self.fetcher.consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS:
                logger.warning("[BLOCKED] %d consecutive blocked responses — stopping crawl for safety",
                                self.fetcher.consecutive_blocks)
                self.store.finish_job(job_id, status="stopped_blocked")
                return job_id

        backfilled = self.store.backfill_area_ids()
        if backfilled:
            logger.info("[INFO] Linked %d development(s) to areas discovered later in this run", backfilled)

        counts = self.store.queue_counts(job_id)
        status = "completed" if counts.get("pending", 0) == 0 else "paused"
        self.store.finish_job(job_id, status=status)
        logger.info("[DONE] job %d finished: %s (processed %d pages this run)", job_id, counts, processed)
        return job_id

    def _get_or_create_job(self, seed_url: str) -> int:
        row = self.store.conn.execute(
            "SELECT id FROM crawl_jobs WHERE seed_url=? AND status IN ('running','paused') "
            "ORDER BY id DESC LIMIT 1",
            (seed_url,),
        ).fetchone()
        if row:
            logger.info("[RESUME] Resuming existing crawl job %d for %s", row["id"], seed_url)
            return row["id"]
        job_id = self.store.create_job(seed_url)
        logger.info("[START] New crawl job %d for %s", job_id, seed_url)
        return job_id

    def _process_one(self, job_id: int, queue_row) -> None:
        url = queue_row["url"]
        result = self.fetcher.fetch(url)
        self.store.record_request()

        if result.error == "not_found":
            self.store.mark_queue(queue_row["id"], "failed", "404 not found")
            self.store.log_error(job_id, url, "404 not found", 404)
            logger.info("[FAILED] 404 %s", url)
            return

        if result.blocked:
            self.store.mark_queue(queue_row["id"], "blocked", result.error)
            self.store.log_blocked(job_id)
            logger.warning("[BLOCKED] %s (%s)", url, result.error)
            return

        if result.html is None:
            self.store.mark_queue(queue_row["id"], "failed", result.error)
            self.store.log_error(job_id, url, result.error or "unknown error", result.status_code)
            logger.warning("[FAILED] %s (%s)", url, result.error)
            return

        soup = BeautifulSoup(result.html, "lxml")
        kind = self._classify(url, soup)
        h = self.store.log_scraped_page(url, result.final_url, result.status_code, result.html,
                                         self.raw_dir, kind)

        try:
            self._extract_and_store(job_id, url, kind, result.html, soup, h)
        except Exception:
            logger.exception("[FAILED] extraction error on %s", url)
            self.store.mark_queue(queue_row["id"], "failed", "extraction error")
            self.store.log_error(job_id, url, "extraction error")
            return

        untrusted_area = kind == "area" and not self.full_dubai_mode and url not in self.trusted_area_urls
        discover_mode_buildings_page = self.mode == "discover" and kind == "buildings"
        if untrusted_area or kind == "unknown" or discover_mode_buildings_page:
            # An area page reached via an untrusted (incidental/tangential) link, e.g.
            # a neighboring-area mention — its own data is stored above, but it is not
            # a valid expansion point for a scoped crawl (see __init__ for the full
            # rationale). A page classify_page couldn't identify as area/development
            # is treated the same way out of caution — better to under-expand from an
            # unrecognized page shape than risk it being another scope-leak vector.
            # In discover mode, a /buildings listing's own development cards are
            # deliberately NOT enqueued — _extract_and_store already turned them into
            # stub rows directly from the listing, which is the whole point of the
            # cheaper discovery pass (see Store.upsert_development_stub).
            newly_queued = 0
        else:
            discovered = self._discover_links(url, soup)
            newly_queued = self.store.enqueue_many(
                job_id, [(link, depth, url) for link, depth in discovered]
            )

        self.store.mark_queue(queue_row["id"], "done")
        self.store.log_processed(job_id)
        logger.info("[SCRAPE] %s -> %s (+%d new URLs)", kind, url, newly_queued)

    def _classify(self, url: str, soup: BeautifulSoup) -> str:
        subpage = area_subpage_kind(url)
        if subpage:
            return subpage  # buildings | amenities | schools | things-to-do
        if is_area_guides_index(url):
            return "area_index"
        kind = parser.classify_page(soup)
        return kind

    def _extract_and_store(self, job_id: int, url: str, kind: str, html: str,
                            soup: BeautifulSoup, content_hash_value: str) -> None:
        if kind == "area":
            page = parser.parse_area_page(html, url, soup=soup)
            area_id = self.store.upsert_area(page, job_id=job_id, content_hash_value=content_hash_value)
            self.store.insert_transactions(page.transactions, development_id=None, area_id=area_id)
            places = parser.parse_mentioned_places(soup)
            if places:
                self._store_mentioned_places(area_id=area_id, development_id=None, places=places)
            if self.full_dubai_mode or url in self.trusted_area_urls:
                # Trust only propagates from an already-trusted area to its own
                # declared children — an untrusted (tangentially-linked) area's
                # subcommunities must not become expansion points either.
                for sc in page.subcommunities:
                    self.trusted_area_urls.add(canonicalize(sc.url))
            logger.info("[DISCOVERY] Found area %s (%d sub-communities)", page.name, len(page.subcommunities))

        elif kind == "development":
            page = parser.parse_development_page(html, url, soup=soup)
            area_id = self._resolve_area_id(page.area_raw)
            dev_id = self.store.upsert_development(page, area_id=area_id, job_id=job_id,
                                                     content_hash_value=content_hash_value)
            self.store.insert_transactions(page.transactions, development_id=dev_id, area_id=area_id)
            places = parser.parse_mentioned_places(soup)
            if places:
                self._store_mentioned_places(area_id=None, development_id=dev_id, places=places)
            unit_line = f" total_units={page.total_units}" if page.total_units is not None else " total_units=UNKNOWN"
            logger.info("[EXTRACT] %s status=%s%s", page.name, page.raw_status, unit_line)

        elif kind == "buildings":
            area_url = url.rsplit("/buildings", 1)[0]
            area_row = self.store.get_area_by_url(canonicalize(area_url))
            cards, stub = parser.parse_buildings_listing(html, soup=soup)
            if area_row:
                stub.url = area_url
                stub.name = area_row["name"]
                self.store.upsert_area(stub, job_id=job_id, content_hash_value=None)
                self.store.mark_missing_developments(
                    {c.url for c in cards}, area_row["id"], job_id
                )
                if self.mode == "discover":
                    for card in cards:
                        self.store.upsert_development_stub(card, area_id=area_row["id"], job_id=job_id)
                    logger.info("[DISCOVERY] Created %d stub development(s) from %s", len(cards), url)
            logger.info("[DISCOVERY] Found %d development URLs on %s", len(cards), url)

        elif kind == "amenities":
            area_url = url.rsplit("/amenities", 1)[0]
            area_row = self.store.get_area_by_url(canonicalize(area_url))
            if area_row:
                amenities = parser.parse_amenities_page(html, soup=soup)
                self._store_amenities(area_row["id"], amenities)
                logger.info("[EXTRACT] %d amenities for %s", len(amenities), area_row["name"])

        elif kind == "schools":
            area_url = url.rsplit("/schools", 1)[0]
            area_row = self.store.get_area_by_url(canonicalize(area_url))
            if area_row:
                schools = parser.parse_schools_page(html, soup=soup)
                self._store_schools(area_row["id"], schools)
                logger.info("[EXTRACT] %d schools for %s", len(schools), area_row["name"])

        # "things-to-do" and "area_index"/"unknown" pages: logged as scraped_pages
        # (raw HTML preserved for future reparsing per brief §13) but have no
        # dedicated structured entities in this MVP's scope.

    def _resolve_area_id(self, area_raw: str | None) -> int | None:
        if not area_raw:
            return None
        row = self.store.conn.execute(
            "SELECT id FROM areas WHERE name=? OR dld_community_name_en=? LIMIT 1",
            (area_raw, area_raw),
        ).fetchone()
        return row["id"] if row else None

    def _store_amenities(self, area_id: int, amenities) -> None:
        from scraper.storage import now
        ts = now()
        for a in amenities:
            self.store.conn.execute(
                "INSERT INTO amenities(area_id, name, category, building_context, distance_text, "
                "source_url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, NULL, ?, ?) "
                "ON CONFLICT(area_id, name, category, building_context) DO UPDATE SET "
                "distance_text=excluded.distance_text, last_seen=excluded.last_seen",
                (area_id, a.name, a.category, a.building_context, a.distance_text, ts, ts),
            )
        self.store.conn.commit()

    def _store_schools(self, area_id: int, schools) -> None:
        from scraper.storage import now
        ts = now()
        for s in schools:
            self.store.conn.execute(
                "INSERT INTO schools(area_id, name, curriculum, rating, distance_text, fees_text, "
                "location_text, source_url, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?) "
                "ON CONFLICT(area_id, name) DO UPDATE SET "
                "rating=excluded.rating, distance_text=excluded.distance_text, "
                "fees_text=excluded.fees_text, location_text=excluded.location_text, last_seen=excluded.last_seen",
                (area_id, s.name, s.curriculum, s.rating, s.distance_text, s.fees_text, s.location_text, ts, ts),
            )
        self.store.conn.commit()

    def _store_mentioned_places(self, area_id: int | None, development_id: int | None, places) -> None:
        # Exactly one of area_id/development_id is set per call, and SQLite's UNIQUE
        # index treats NULLs as distinct from each other (so ON CONFLICT would never
        # fire and re-crawls would keep inserting duplicates) — do a NULL-safe manual
        # upsert with `IS` instead.
        from scraper.storage import now
        ts = now()
        for p in places:
            section = p.section or "Transport & Access"  # column is NOT NULL
            existing = self.store.conn.execute(
                "SELECT id FROM mentioned_places WHERE source_area_id IS ? AND "
                "source_development_id IS ? AND name = ? AND section = ?",
                (area_id, development_id, p.name, section),
            ).fetchone()
            if existing:
                self.store.conn.execute(
                    "UPDATE mentioned_places SET linked_url = ?, context_sentence = ? WHERE id = ?",
                    (p.linked_url, p.context_sentence, existing["id"]),
                )
            else:
                self.store.conn.execute(
                    "INSERT INTO mentioned_places(source_area_id, source_development_id, name, "
                    "linked_url, context_sentence, section, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (area_id, development_id, p.name, p.linked_url, p.context_sentence, section, ts),
                )
        self.store.conn.commit()

    def _discover_links(self, source_url: str, soup: BeautifulSoup) -> list[tuple[str, int]]:
        # Scope link discovery to <main> so the site-wide sidebar mega-menu (present on
        # every page, linking to every Dubai area regardless of the current page) can't
        # blow an area-scoped crawl out into unrelated areas. See url_utils.py notes.
        scope = soup.find("main") or soup
        out = []
        for a in scope.find_all("a", href=True):
            href = canonicalize(a["href"], base=source_url)
            if not is_allowed(href):
                continue
            if not self.full_dubai_mode and is_area_guides_index(href):
                # Every area/development page's breadcrumb links back to the Dubai-wide
                # directory; skip it in scoped mode so one seed area doesn't cascade
                # into the whole site (see run()'s comment above).
                continue
            out.append((href, 1))
        return out
