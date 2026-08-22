"""SQLite storage: schema, upserts, deduplication, and change tracking.

Design notes (see brief §14-17):
  - Stable internal IDs are SQLite `INTEGER PRIMARY KEY` autoincrement rowids; the
    Propsearch URL (canonicalized) is the natural/business key used for dedup, never
    the display name.
  - A record is a "development" if it is not itself a sub-building of another record
    (no `master_development_url`); a record IS a "building" row (in `buildings`) only
    when a parent development explicitly enumerates it as a sub-building (brief §7 —
    do not assume 1 development = 1 building, but do not fabricate a second row for
    the common case where a development page describes exactly one physical building).
  - Every upsert compares old vs new field values and records a `change_log` row per
    changed field, enabling incremental-update reporting (brief §16).
  - Raw HTML is written to `data/raw/` (one file per fetch), not stored as a DB blob,
    keeping the DB itself small and queryable (brief §13/§14).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from scraper.models import AreaPage, DevelopmentPage
from scraper.normalizer import classify_area_type, normalize_alias, normalize_status, split_aliases

logger = logging.getLogger("propsearch.storage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS crawl_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    pages_discovered INTEGER NOT NULL DEFAULT 0,
    pages_processed INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    pages_blocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS crawl_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES crawl_jobs(id),
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|in_progress|done|failed|blocked
    depth INTEGER NOT NULL DEFAULT 0,
    discovered_from TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, url)
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON crawl_queue(job_id, status);

CREATE TABLE IF NOT EXISTS scraped_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL,
    final_url TEXT,
    http_status INTEGER,
    scraped_at TEXT NOT NULL,
    content_hash TEXT,
    raw_html_path TEXT,
    page_kind TEXT
);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_url ON scraped_pages(url);

CREATE TABLE IF NOT EXISTS developers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT UNIQUE,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    slug TEXT,
    name TEXT NOT NULL,
    parent_area_name TEXT,
    description TEXT,
    also_known_as TEXT,
    developer_id INTEGER REFERENCES developers(id),
    developer_raw TEXT,
    dld_community_code TEXT,
    dld_community_name_en TEXT,
    dld_community_name_ar TEXT,
    dld_buildings INTEGER,
    dld_villas INTEGER,
    dld_residential_units INTEGER,
    dld_commercial_units INTEGER,
    propsearch_dev_summary_raw TEXT,
    propsearch_dev_total INTEGER,
    propsearch_dev_completed INTEGER,
    propsearch_dev_under_construction INTEGER,
    propsearch_dev_planned INTEGER,
    propsearch_dev_on_hold INTEGER,
    propsearch_dev_cancelled INTEGER,
    latitude REAL,
    longitude REAL,
    sub_community_count INTEGER,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    content_hash TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS developments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    slug TEXT,
    name TEXT NOT NULL,
    building_type_raw TEXT,
    is_multi_building INTEGER NOT NULL DEFAULT 0,
    area_id INTEGER REFERENCES areas(id),
    area_raw TEXT,
    master_development_id INTEGER REFERENCES developments(id),
    master_development_url TEXT,
    developer_id INTEGER REFERENCES developers(id),
    developer_raw TEXT,
    raw_status TEXT,
    normalized_status TEXT,
    storeys_raw TEXT,
    total_units INTEGER,
    total_units_raw TEXT,
    construction_start_raw TEXT,
    construction_start_date TEXT,
    estimated_completion_raw TEXT,
    estimated_completion_date TEXT,
    actual_completion_raw TEXT,
    actual_completion_date TEXT,
    first_trace_raw TEXT,
    first_trace_date TEXT,
    project_value_aed REAL,
    project_value_usd REAL,
    project_value_raw TEXT,
    plot_reference TEXT,
    overview_text TEXT,
    history_text TEXT,
    timeline_summary_raw TEXT,
    key_dates_raw TEXT,
    additional_info_json TEXT,
    official_website TEXT,
    latitude REAL,
    longitude REAL,
    is_active INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    content_hash TEXT,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_developments_area ON developments(area_id);
CREATE INDEX IF NOT EXISTS idx_developments_master ON developments(master_development_id);

CREATE TABLE IF NOT EXISTS buildings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id INTEGER NOT NULL REFERENCES developments(id),
    url TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    storeys_raw TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_buildings_dev ON buildings(development_id);

CREATE TABLE IF NOT EXISTS unit_supply (
    development_id INTEGER PRIMARY KEY REFERENCES developments(id),
    total_units INTEGER,
    residential_units INTEGER,
    commercial_units INTEGER,
    retail_units INTEGER,
    hotel_units INTEGER,
    offices INTEGER,
    shops INTEGER,
    studios INTEGER,
    beds_1 INTEGER,
    beds_2 INTEGER,
    beds_3 INTEGER,
    beds_4 INTEGER,
    beds_5_plus INTEGER,
    apartments INTEGER,
    duplexes INTEGER,
    penthouses INTEGER,
    villas INTEGER,
    townhouses INTEGER,
    last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT,
    development_id INTEGER REFERENCES developments(id),
    area_id INTEGER REFERENCES areas(id),
    transaction_date TEXT,
    transaction_date_raw TEXT,
    price_aed REAL,
    price_per_sqft_aed REAL,
    price_per_sqm_aed REAL,
    size_sqft REAL,
    room_type TEXT,
    property_type TEXT,
    property_subtype TEXT,
    property_use TEXT,
    registration_type TEXT,
    transaction_type TEXT,
    transaction_group TEXT,
    building_name_raw TEXT,
    project_raw TEXT,
    master_project_raw TEXT,
    area_raw TEXT,
    num_sellers INTEGER,
    num_buyers INTEGER,
    parking TEXT,
    source_url TEXT,
    first_seen TEXT NOT NULL,
    UNIQUE(transaction_id, source_url)
);
CREATE INDEX IF NOT EXISTS idx_transactions_dev ON transactions(development_id);

CREATE TABLE IF NOT EXISTS amenities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER REFERENCES areas(id),
    name TEXT NOT NULL,
    category TEXT,
    building_context TEXT,
    distance_text TEXT,
    source_url TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(area_id, name, category, building_context)
);

CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER REFERENCES areas(id),
    name TEXT NOT NULL,
    curriculum TEXT,
    rating TEXT,
    distance_text TEXT,
    fees_text TEXT,
    location_text TEXT,
    source_url TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(area_id, name)
);

CREATE TABLE IF NOT EXISTS construction_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id INTEGER NOT NULL REFERENCES developments(id),
    role TEXT,
    company_name TEXT,
    company_url TEXT,
    first_seen TEXT NOT NULL,
    UNIQUE(development_id, role, company_name)
);

CREATE TABLE IF NOT EXISTS construction_milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id INTEGER NOT NULL REFERENCES developments(id),
    label TEXT NOT NULL,
    date_raw TEXT,
    date_parsed TEXT,
    first_seen TEXT NOT NULL,
    UNIQUE(development_id, label)
);

CREATE TABLE IF NOT EXISTS construction_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id INTEGER REFERENCES developments(id),
    area_id INTEGER REFERENCES areas(id),
    date_raw TEXT,
    date_parsed TEXT,
    description TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    UNIQUE(development_id, area_id, description)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    development_id INTEGER REFERENCES developments(id),
    area_id INTEGER REFERENCES areas(id),
    doc_type TEXT NOT NULL,
    label TEXT,
    photo_count INTEGER,
    url TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(development_id, area_id, doc_type)
);

CREATE TABLE IF NOT EXISTS sub_communities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_area_id INTEGER NOT NULL REFERENCES areas(id),
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    raw_status TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE(parent_area_id, url)
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,   -- area|development|building
    entity_id INTEGER NOT NULL,
    entity_url TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    detected_at TEXT NOT NULL,
    job_id INTEGER REFERENCES crawl_jobs(id),
    change_kind TEXT NOT NULL DEFAULT 'field_changed'  -- new_record|field_changed|disappeared
);
CREATE INDEX IF NOT EXISTS idx_change_log_time ON change_log(detected_at);

CREATE TABLE IF NOT EXISTS crawl_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES crawl_jobs(id),
    url TEXT NOT NULL,
    error TEXT NOT NULL,
    http_status INTEGER,
    occurred_at TEXT NOT NULL
);

-- Daily request budget (brief §20/§26): one row per UTC date, incremented on every
-- fetch attempt (not just successes) so a run that mostly 404s/errors still counts
-- against the day's ceiling.
CREATE TABLE IF NOT EXISTS crawl_budget (
    date TEXT PRIMARY KEY,
    requests_used INTEGER NOT NULL DEFAULT 0
);

-- Place names mentioned in an area/development's free-text prose (Transport &
-- Access, Overview) — captured as mentions, not fabricated structured POI records,
-- because Propsearch does not expose malls/metro/hospitals as separate structured
-- data (verified against real cached HTML; see PROPSEARCH_STRUCTURE.md).
CREATE TABLE IF NOT EXISTS mentioned_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_area_id INTEGER REFERENCES areas(id),
    source_development_id INTEGER REFERENCES developments(id),
    name TEXT NOT NULL,
    linked_url TEXT,
    context_sentence TEXT,
    section TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    UNIQUE(source_area_id, source_development_id, name, section)
);

-- Proper alias structure for an area's alternate names, replacing the flat
-- also_known_as string as the source of truth for matching (also_known_as is kept
-- as-is for backward compatibility with existing consumers of the areas table).
CREATE TABLE IF NOT EXISTS entity_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_id INTEGER NOT NULL REFERENCES areas(id),
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    alias_type TEXT NOT NULL DEFAULT 'source_name',
    source TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    is_manual INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(area_id, normalized_alias)
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


class Store:
    def __init__(self, db_path: str | Path, migrate: bool = True):
        """`migrate=False` skips schema/backfill migrations — for read-only callers
        (e.g. `--status`) that must not contend for the write lock with a concurrently
        running crawl. The backfills scale with how many pages have been scraped
        since the *last* Store() construction (not a fixed one-time cost), so a
        status check running them too could itself hold the writer lock long enough
        to starve the live crawler even with a generous busy_timeout — this avoids
        that class of contention entirely rather than just widening the timeout.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        # WAL + NORMAL sync: a crawl does thousands of small writes (queue inserts,
        # transaction rows, change_log entries); the default DELETE journal mode
        # fsyncs on every commit and was the dominant cost in early testing (a single
        # ~2MB /buildings listing page enqueuing ~900 URLs took minutes). Durability
        # tradeoff is fine for a local research tool — worst case on a crash is redoing
        # the last few seconds of one crawl run, and progress is checkpointed anyway.
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        # WAL allows one writer at a time; without a busy_timeout, a second process
        # (e.g. `--status` while a crawl is running — its own Store() init runs
        # write-doing backfills, not just reads) hits "database is locked" and
        # crashes immediately instead of just waiting a moment for the other writer.
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.executescript(SCHEMA)
        self._migrate_schema()
        if migrate:
            self._migrate_data()
        self.conn.commit()

    def _migrate_schema(self) -> None:
        """Additive, idempotent column migrations for tables that predate a given
        column. SQLite's ALTER TABLE ADD COLUMN has no IF NOT EXISTS, so each column
        is checked via PRAGMA table_info first. Always runs (even with migrate=False)
        — cheap catalog-only checks, and every column referenced elsewhere in Store
        must exist regardless of whether the slower data backfills below also run.
        """
        migrations = [
            ("areas", "area_type", "TEXT NOT NULL DEFAULT 'community'"),
            ("areas", "is_stub", "INTEGER NOT NULL DEFAULT 0"),
            ("areas", "enriched_at", "TEXT"),
            ("developments", "is_stub", "INTEGER NOT NULL DEFAULT 0"),
            ("developments", "enriched_at", "TEXT"),
            ("areas", "hero_image_url", "TEXT"),
            ("developments", "hero_image_url", "TEXT"),
            ("sub_communities", "image_url", "TEXT"),
            ("documents", "photo_urls_json", "TEXT"),
            ("scraped_pages", "mentions_backfilled", "INTEGER NOT NULL DEFAULT 0"),
            ("scraped_pages", "images_backfilled", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for table, column, coltype in migrations:
            existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
                logger.info("[MIGRATE] Added column %s.%s", table, column)

    def _migrate_data(self) -> None:
        """The backfill passes — these scale with how much a live crawl has grown the
        database since the last Store() construction, so a read-only caller (like
        `--status`) must skip them via migrate=False rather than contend for the
        write lock with a concurrently running crawl (see Store.__init__ docstring).
        """
        self.backfill_area_types()
        self.backfill_aliases()
        self.backfill_mentioned_places()
        self.backfill_image_urls()

    def backfill_area_types(self) -> int:
        """Reclassifies every existing area row's area_type from its name — cheap
        (name-only, no re-fetch needed) and idempotent, so it's safe to run on every
        Store startup. This is what fixes rows scraped before area_type existed (or
        before classify_area_type's rules were extended) without needing a re-crawl.
        """
        rows = self.conn.execute("SELECT id, name, area_type FROM areas").fetchall()
        changed = 0
        for row in rows:
            correct = classify_area_type(row["name"])
            if row["area_type"] != correct:
                self.conn.execute("UPDATE areas SET area_type=? WHERE id=?", (correct, row["id"]))
                changed += 1
        if changed:
            self.conn.commit()
            logger.info("[MIGRATE] Reclassified area_type for %d area(s)", changed)
        return changed

    def backfill_aliases(self) -> int:
        """Turns each area's flat also_known_as string (and, when present and
        distinct, its DLD community name) into proper entity_aliases rows —
        idempotent (ON CONFLICT DO NOTHING on the area_id+normalized_alias unique
        constraint), safe to run on every Store startup.
        """
        ts = now()
        rows = self.conn.execute(
            "SELECT id, name, also_known_as, dld_community_name_en FROM areas"
        ).fetchall()
        added = 0
        for row in rows:
            candidates: list[tuple[str, str]] = []  # (alias, alias_type)
            for alias in split_aliases(row["also_known_as"]):
                candidates.append((alias, "also_known_as"))
            dld_name = row["dld_community_name_en"]
            if dld_name and normalize_alias(dld_name) != normalize_alias(row["name"] or ""):
                candidates.append((dld_name, "dld_name"))
            for alias, alias_type in candidates:
                cur = self.conn.execute(
                    "INSERT INTO entity_aliases(area_id, alias, normalized_alias, alias_type, source, "
                    "confidence, is_manual, created_at) VALUES (?, ?, ?, ?, 'propsearch', 1.0, 0, ?) "
                    "ON CONFLICT(area_id, normalized_alias) DO NOTHING",
                    (row["id"], alias, normalize_alias(alias), alias_type, ts),
                )
                added += cur.rowcount
        if added:
            self.conn.commit()
            logger.info("[MIGRATE] Added %d entity alias row(s)", added)
        return added

    def backfill_mentioned_places(self) -> int:
        """Extracts Transport & Access prose-link mentions from already-cached raw HTML
        (scraped_pages.raw_html_path) for area/development rows scraped before this
        feature existed — no re-fetch needed, matching the mall/landmark backfill's
        approach. Idempotent (checked via the same NULL-safe existence lookup used
        during a live crawl). Filtered to scraped_pages rows not yet marked
        `mentions_backfilled` so cost shrinks to ~zero after the first run instead of
        re-parsing every cached page's HTML on every Store startup forever.
        """
        from bs4 import BeautifulSoup

        from scraper.parser import parse_mentioned_places

        added = 0
        for entity_table, is_area in (("areas", True), ("developments", False)):
            page_kind = "area" if is_area else "development"
            rows = self.conn.execute(
                "SELECT sp.id AS scraped_page_id, e.id AS entity_id, sp.raw_html_path FROM scraped_pages sp "
                f"JOIN {entity_table} e ON e.url = sp.url "
                "WHERE sp.page_kind = ? AND sp.raw_html_path IS NOT NULL AND sp.mentions_backfilled = 0",
                (page_kind,),
            ).fetchall()
            for row in rows:
                path = Path(row["raw_html_path"])
                if path.exists():
                    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
                    area_id = row["entity_id"] if is_area else None
                    dev_id = row["entity_id"] if not is_area else None
                    for p in parse_mentioned_places(soup):
                        section = p.section or "Transport & Access"
                        existing = self.conn.execute(
                            "SELECT id FROM mentioned_places WHERE source_area_id IS ? AND "
                            "source_development_id IS ? AND name = ? AND section = ?",
                            (area_id, dev_id, p.name, section),
                        ).fetchone()
                        if existing:
                            continue
                        self.conn.execute(
                            "INSERT INTO mentioned_places(source_area_id, source_development_id, name, "
                            "linked_url, context_sentence, section, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (area_id, dev_id, p.name, p.linked_url, p.context_sentence, section, now()),
                        )
                        added += 1
                self.conn.execute(
                    "UPDATE scraped_pages SET mentions_backfilled = 1 WHERE id = ?", (row["scraped_page_id"],)
                )
        if added:
            logger.info("[MIGRATE] Backfilled %d mentioned_place row(s) from cached HTML", added)
        self.conn.commit()
        return added

    def backfill_image_urls(self) -> int:
        """Populates hero_image_url / sub_communities.image_url / documents.photo_urls_json
        for area/development rows scraped before image-URL capture existed, by
        re-parsing already-cached raw HTML — no re-fetch needed, same approach as
        backfill_mentioned_places. Reuses the normal upsert_area/upsert_development
        path (safe: _merge_keep_existing only ever fills in previously-missing fields
        from a fresh parse, never blanks existing data). Filtered by a dedicated
        `images_backfilled` marker (NOT by "hero_image_url IS NULL" — a handful of
        real pages genuinely have no matching hero image, e.g. cancelled/placeholder
        listings, and using the nullable field itself as the "done" signal would
        re-parse those specific pages forever since they'd never stop being NULL).
        """
        from bs4 import BeautifulSoup

        from scraper.parser import parse_area_page, parse_development_page

        updated = 0
        area_rows = self.conn.execute(
            "SELECT a.id, a.url, sp.id AS scraped_page_id, sp.raw_html_path FROM areas a "
            "JOIN scraped_pages sp ON sp.url = a.url AND sp.page_kind = 'area' "
            "WHERE sp.images_backfilled = 0 AND sp.raw_html_path IS NOT NULL"
        ).fetchall()
        for row in area_rows:
            path = Path(row["raw_html_path"])
            if path.exists():
                html = path.read_text(encoding="utf-8")
                page = parse_area_page(html, row["url"], soup=BeautifulSoup(html, "lxml"))
                self.upsert_area(page)
                updated += 1
            self.conn.execute(
                "UPDATE scraped_pages SET images_backfilled = 1 WHERE id = ?", (row["scraped_page_id"],)
            )

        dev_rows = self.conn.execute(
            "SELECT d.id, d.url, d.area_id, sp.id AS scraped_page_id, sp.raw_html_path FROM developments d "
            "JOIN scraped_pages sp ON sp.url = d.url AND sp.page_kind = 'development' "
            "WHERE sp.images_backfilled = 0 AND sp.raw_html_path IS NOT NULL"
        ).fetchall()
        for row in dev_rows:
            path = Path(row["raw_html_path"])
            if path.exists():
                html = path.read_text(encoding="utf-8")
                page = parse_development_page(html, row["url"], soup=BeautifulSoup(html, "lxml"))
                self.upsert_development(page, area_id=row["area_id"])
                updated += 1
            self.conn.execute(
                "UPDATE scraped_pages SET images_backfilled = 1 WHERE id = ?", (row["scraped_page_id"],)
            )

        if updated:
            logger.info("[MIGRATE] Backfilled image URLs for %d row(s) from cached HTML", updated)
        self.conn.commit()
        return updated

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # -- daily request budget ------------------------------------------------

    def record_request(self) -> int:
        """Increments today's (UTC date) request counter and returns the new total.
        Called once per queue item processed (not per raw HTTP retry attempt —
        that's Fetcher-internal detail the budget doesn't need to see).
        """
        today = time.strftime("%Y-%m-%d", time.gmtime())
        self.conn.execute(
            "INSERT INTO crawl_budget(date, requests_used) VALUES (?, 1) "
            "ON CONFLICT(date) DO UPDATE SET requests_used = requests_used + 1",
            (today,),
        )
        self.conn.commit()
        return self.requests_used_today()

    def requests_used_today(self) -> int:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        row = self.conn.execute("SELECT requests_used FROM crawl_budget WHERE date = ?", (today,)).fetchone()
        return row["requests_used"] if row else 0

    # -- crawl jobs / queue -------------------------------------------------

    def create_job(self, seed_url: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO crawl_jobs(seed_url, started_at, status) VALUES (?, ?, 'running')",
            (seed_url, now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_job(self, job_id: int, status: str = "completed"):
        self.conn.execute(
            "UPDATE crawl_jobs SET status=?, finished_at=? WHERE id=?",
            (status, now(), job_id),
        )
        self.conn.commit()

    def job_stats(self, job_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM crawl_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else {}

    def entity_counts(self) -> dict:
        """Whole-database entity totals for the --status report (brief §53) — always
        a live COUNT(*), never a cached/stale number.
        """
        def count(sql: str) -> int:
            return self.conn.execute(sql).fetchone()[0]

        return {
            "areas_total": count("SELECT COUNT(*) FROM areas"),
            "areas_community": count("SELECT COUNT(*) FROM areas WHERE area_type='community'"),
            "areas_landmark": count("SELECT COUNT(*) FROM areas WHERE area_type='landmark'"),
            "areas_mall": count("SELECT COUNT(*) FROM areas WHERE area_type='mall'"),
            "sub_communities": count("SELECT COUNT(*) FROM sub_communities"),
            "developments_total": count("SELECT COUNT(*) FROM developments WHERE is_active=1"),
            "developments_enriched": count("SELECT COUNT(*) FROM developments WHERE is_active=1 AND is_stub=0"),
            "developments_stub": count("SELECT COUNT(*) FROM developments WHERE is_active=1 AND is_stub=1"),
            "buildings": count("SELECT COUNT(*) FROM buildings"),
            "developers": count("SELECT COUNT(*) FROM developers"),
            "schools": count("SELECT COUNT(*) FROM schools"),
            "amenities": count("SELECT COUNT(*) FROM amenities"),
            "mentioned_places": count("SELECT COUNT(*) FROM mentioned_places"),
            "entity_aliases": count("SELECT COUNT(*) FROM entity_aliases"),
            "transactions": count("SELECT COUNT(*) FROM transactions"),
        }

    def enqueue(self, job_id: int, url: str, depth: int, discovered_from: str | None) -> bool:
        """Single-URL enqueue, used for the initial seed. For discovered-link batches
        (often hundreds of URLs from one page), use `enqueue_many` instead — this
        method commits immediately and is too slow to call in a tight loop.
        """
        try:
            self.conn.execute(
                "INSERT INTO crawl_queue(job_id, url, depth, discovered_from, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, url, depth, discovered_from, now(), now()),
            )
            self.conn.execute(
                "UPDATE crawl_jobs SET pages_discovered = pages_discovered + 1 WHERE id=?", (job_id,)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False  # already queued for this job (dedup / no crawler traps)

    def enqueue_many(self, job_id: int, links: list[tuple[str, int, str | None]]) -> int:
        """Bulk-insert discovered links in a single transaction. `INSERT OR IGNORE`
        handles dedup against the `UNIQUE(job_id, url)` constraint (already-queued
        links, and crawler-trap loops, are silently skipped) without the per-row
        try/except + commit cost of calling `enqueue` in a loop.
        """
        if not links:
            return 0
        ts = now()
        rows = [(job_id, url, depth, discovered_from, ts, ts) for url, depth, discovered_from in links]
        before = self.conn.total_changes
        self.conn.executemany(
            "INSERT OR IGNORE INTO crawl_queue(job_id, url, depth, discovered_from, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        inserted = self.conn.total_changes - before
        if inserted:
            self.conn.execute(
                "UPDATE crawl_jobs SET pages_discovered = pages_discovered + ? WHERE id=?", (inserted, job_id)
            )
        self.conn.commit()
        return inserted

    def next_pending(self, job_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM crawl_queue WHERE job_id=? AND status='pending' ORDER BY id LIMIT 1",
            (job_id,),
        ).fetchone()

    def mark_queue(self, queue_id: int, status: str, error: str | None = None):
        self.conn.execute(
            "UPDATE crawl_queue SET status=?, last_error=?, updated_at=?, "
            "attempts = attempts + 1 WHERE id=?",
            (status, error, now(), queue_id),
        )
        self.conn.commit()

    def queue_counts(self, job_id: int) -> dict:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) c FROM crawl_queue WHERE job_id=? GROUP BY status", (job_id,)
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}

    def pending_retryable(self, job_id: int, max_attempts: int = 3) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM crawl_queue WHERE job_id=? AND status='failed' AND attempts < ?",
            (job_id, max_attempts),
        ).fetchall()

    # -- raw page log ---------------------------------------------------

    def log_scraped_page(self, url: str, final_url: str, http_status: int | None,
                          html: str | None, raw_dir: Path, page_kind: str) -> str | None:
        raw_path = None
        h = content_hash(html) if html else None
        if html:
            raw_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{h[:16]}.html"
            raw_path = str(raw_dir / fname)
            if not Path(raw_path).exists():
                Path(raw_path).write_text(html, encoding="utf-8")
        self.conn.execute(
            "INSERT INTO scraped_pages(url, final_url, http_status, scraped_at, content_hash, "
            "raw_html_path, page_kind) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (url, final_url, http_status, now(), h, raw_path, page_kind),
        )
        self.conn.commit()
        return h

    def log_error(self, job_id: int, url: str, error: str, http_status: int | None = None):
        self.conn.execute(
            "INSERT INTO crawl_errors(job_id, url, error, http_status, occurred_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, url, error, http_status, now()),
        )
        self.conn.execute("UPDATE crawl_jobs SET pages_failed = pages_failed + 1 WHERE id=?", (job_id,))
        self.conn.commit()

    def log_blocked(self, job_id: int):
        self.conn.execute("UPDATE crawl_jobs SET pages_blocked = pages_blocked + 1 WHERE id=?", (job_id,))
        self.conn.commit()

    def log_processed(self, job_id: int):
        self.conn.execute("UPDATE crawl_jobs SET pages_processed = pages_processed + 1 WHERE id=?", (job_id,))
        self.conn.commit()

    # -- developers -------------------------------------------------------

    def upsert_developer(self, name: str | None, url: str | None) -> int | None:
        if not name and not url:
            return None
        ts = now()
        if url:
            row = self.conn.execute("SELECT id FROM developers WHERE url=?", (url,)).fetchone()
            if row:
                self.conn.execute("UPDATE developers SET last_seen=?, name=? WHERE id=?", (ts, name or row["id"], row["id"]))
                self.conn.commit()
                return row["id"]
        cur = self.conn.execute(
            "INSERT INTO developers(name, url, first_seen, last_seen) VALUES (?, ?, ?, ?)",
            (name or "Unknown", url, ts, ts),
        )
        self.conn.commit()
        return cur.lastrowid

    # -- generic diff/upsert helper ---------------------------------------

    def _record_changes(self, job_id: int | None, entity_type: str, entity_id: int, entity_url: str,
                         old_row: sqlite3.Row | None, new_values: dict, tracked_fields: list[str]):
        ts = now()
        if old_row is None:
            self.conn.execute(
                "INSERT INTO change_log(entity_type, entity_id, entity_url, field_name, old_value, "
                "new_value, detected_at, job_id, change_kind) VALUES (?, ?, ?, 'record', NULL, ?, ?, ?, 'new_record')",
                (entity_type, entity_id, entity_url, entity_url, ts, job_id),
            )
            return
        for field in tracked_fields:
            old_val = old_row[field] if field in old_row.keys() else None
            new_val = new_values.get(field)
            if _norm_cmp(old_val) != _norm_cmp(new_val):
                self.conn.execute(
                    "INSERT INTO change_log(entity_type, entity_id, entity_url, field_name, old_value, "
                    "new_value, detected_at, job_id, change_kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'field_changed')",
                    (entity_type, entity_id, entity_url, field, _str_or_none(old_val), _str_or_none(new_val), ts, job_id),
                )

    # -- areas --------------------------------------------------------------

    AREA_TRACKED_FIELDS = [
        "description", "also_known_as", "developer_raw", "dld_buildings", "dld_villas",
        "dld_residential_units", "dld_commercial_units", "propsearch_dev_total",
        "propsearch_dev_completed", "propsearch_dev_under_construction",
        "propsearch_dev_planned", "propsearch_dev_on_hold", "propsearch_dev_cancelled",
    ]

    def upsert_area(self, page: AreaPage, job_id: int | None = None, content_hash_value: str | None = None) -> int:
        ts = now()
        developer_id = self.upsert_developer(
            page.developer_link.text if page.developer_link else None,
            page.developer_link.url if page.developer_link else None,
        )
        slug = page.url.rstrip("/").rsplit("/", 1)[-1] if page.url else None
        values = dict(
            slug=slug, name=page.name, parent_area_name=page.parent_area,
            description=page.overview_text, also_known_as=page.also_known_as,
            developer_id=developer_id, developer_raw=page.developer_raw,
            dld_community_code=page.dld_community_code,
            dld_community_name_en=page.dld_community_name_en,
            dld_community_name_ar=page.dld_community_name_ar,
            dld_buildings=page.dld_buildings, dld_villas=page.dld_villas,
            dld_residential_units=page.dld_residential_units,
            dld_commercial_units=page.dld_commercial_units,
            propsearch_dev_summary_raw=page.propsearch_dev_summary_raw,
            propsearch_dev_total=page.propsearch_dev_total,
            propsearch_dev_completed=page.propsearch_dev_completed,
            propsearch_dev_under_construction=page.propsearch_dev_under_construction,
            propsearch_dev_planned=page.propsearch_dev_planned,
            propsearch_dev_on_hold=page.propsearch_dev_on_hold,
            propsearch_dev_cancelled=page.propsearch_dev_cancelled,
            latitude=page.latitude, longitude=page.longitude,
            sub_community_count=len(page.subcommunities),
            area_type=classify_area_type(page.name),
            hero_image_url=page.hero_image_url,
            content_hash=content_hash_value,
            raw_json=json.dumps(_safe_asdict(page), default=str),
        )
        existing = self.conn.execute("SELECT * FROM areas WHERE url=?", (page.url,)).fetchone()
        if existing:
            area_id = existing["id"]
            # Never let a partial re-scrape (e.g. from a sub-page that lacks the full
            # COMMUNITY widget) blank out previously-known data.
            merged = _merge_keep_existing(existing, values)
            self._record_changes(job_id, "area", area_id, page.url, existing, merged, self.AREA_TRACKED_FIELDS)
            set_clause = ", ".join(f"{k}=?" for k in merged) + ", last_seen=?"
            self.conn.execute(
                f"UPDATE areas SET {set_clause} WHERE id=?",
                (*merged.values(), ts, area_id),
            )
        else:
            cols = list(values.keys()) + ["url", "first_seen", "last_seen"]
            placeholders = ", ".join("?" for _ in cols)
            cur = self.conn.execute(
                f"INSERT INTO areas({', '.join(cols)}) VALUES ({placeholders})",
                (*values.values(), page.url, ts, ts),
            )
            area_id = cur.lastrowid
            self._record_changes(job_id, "area", area_id, page.url, None, values, self.AREA_TRACKED_FIELDS)
        self.conn.commit()

        for sc in page.subcommunities:
            self.conn.execute(
                "INSERT INTO sub_communities(parent_area_id, name, url, raw_status, image_url, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(parent_area_id, url) DO UPDATE SET "
                "raw_status=excluded.raw_status, name=excluded.name, "
                "image_url=COALESCE(excluded.image_url, sub_communities.image_url), last_seen=excluded.last_seen",
                (area_id, sc.name, sc.url, sc.raw_status, sc.image_url, ts, ts),
            )
        for doc in page.documents:
            self._upsert_document(area_id=area_id, development_id=None, doc=doc)
        self.conn.commit()
        return area_id

    def get_area_by_url(self, url: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM areas WHERE url=?", (url,)).fetchone()

    # -- developments ---------------------------------------------------

    DEV_TRACKED_FIELDS = [
        "raw_status", "normalized_status", "total_units", "estimated_completion_date",
        "actual_completion_date", "developer_raw", "storeys_raw", "is_active",
    ]

    def upsert_development(self, page: DevelopmentPage, area_id: int | None, job_id: int | None = None,
                            content_hash_value: str | None = None) -> int:
        ts = now()
        developer_id = self.upsert_developer(
            page.developer_link.text if page.developer_link else None,
            page.developer_link.url if page.developer_link else None,
        )
        master_id = None
        if page.master_development_link:
            master_row = self.conn.execute(
                "SELECT id FROM developments WHERE url=?", (page.master_development_link.url,)
            ).fetchone()
            master_id = master_row["id"] if master_row else None

        milestones_by_label = {m.label: m for m in page.milestones}
        construction_start = milestones_by_label.get("Construction Started")
        estimated_completion = milestones_by_label.get("Estimated Completion")
        actual_completion = milestones_by_label.get("Construction Finished")
        first_trace = milestones_by_label.get("First Trace")

        slug = page.url.rstrip("/").rsplit("/", 1)[-1] if page.url else None
        normalized = normalize_status(page.raw_status)
        values = dict(
            slug=slug, name=page.name, building_type_raw=page.building_type_raw,
            is_multi_building=int(page.is_multi_building), area_id=area_id, area_raw=page.area_raw,
            master_development_id=master_id,
            master_development_url=page.master_development_link.url if page.master_development_link else None,
            developer_id=developer_id, developer_raw=page.developer_raw,
            raw_status=page.raw_status, normalized_status=normalized, storeys_raw=page.storeys_raw,
            total_units=page.total_units, total_units_raw=page.total_units_raw,
            construction_start_raw=construction_start.date_raw if construction_start else None,
            construction_start_date=construction_start.date_parsed if construction_start else None,
            estimated_completion_raw=estimated_completion.date_raw if estimated_completion else None,
            estimated_completion_date=estimated_completion.date_parsed if estimated_completion else None,
            actual_completion_raw=actual_completion.date_raw if actual_completion else None,
            actual_completion_date=actual_completion.date_parsed if actual_completion else None,
            first_trace_raw=first_trace.date_raw if first_trace else None,
            first_trace_date=first_trace.date_parsed if first_trace else None,
            project_value_aed=page.project_value_aed, project_value_usd=page.project_value_usd,
            project_value_raw=page.project_value_raw, plot_reference=page.plot_reference,
            overview_text=page.overview_text, history_text=page.history_text,
            timeline_summary_raw=page.timeline_summary_raw, key_dates_raw=page.key_dates_raw,
            additional_info_json=json.dumps(page.additional_info),
            official_website=page.official_website,
            latitude=page.latitude, longitude=page.longitude,
            hero_image_url=page.hero_image_url,
            is_active=1,
            is_stub=0, enriched_at=ts,
            content_hash=content_hash_value,
            raw_json=json.dumps(_safe_asdict(page), default=str),
        )
        existing = self.conn.execute("SELECT * FROM developments WHERE url=?", (page.url,)).fetchone()
        if existing:
            dev_id = existing["id"]
            merged = _merge_keep_existing(existing, values)
            self._record_changes(job_id, "development", dev_id, page.url, existing, merged, self.DEV_TRACKED_FIELDS)
            set_clause = ", ".join(f"{k}=?" for k in merged) + ", last_seen=?"
            self.conn.execute(f"UPDATE developments SET {set_clause} WHERE id=?", (*merged.values(), ts, dev_id))
        else:
            cols = list(values.keys()) + ["url", "first_seen", "last_seen"]
            placeholders = ", ".join("?" for _ in cols)
            cur = self.conn.execute(
                f"INSERT INTO developments({', '.join(cols)}) VALUES ({placeholders})",
                (*values.values(), page.url, ts, ts),
            )
            dev_id = cur.lastrowid
            self._record_changes(job_id, "development", dev_id, page.url, None, values, self.DEV_TRACKED_FIELDS)
        self.conn.commit()

        # Sub-buildings: only materialize a `buildings` row when Propsearch explicitly
        # names a child building (brief §7 — don't assume 1:1, don't fabricate either).
        for link in page.sub_building_links:
            self.conn.execute(
                "INSERT INTO buildings(development_id, url, name, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET "
                "name=excluded.name, development_id=excluded.development_id, last_seen=excluded.last_seen",
                (dev_id, link.url, link.text, ts, ts),
            )

        for company in page.companies:
            self.conn.execute(
                "INSERT INTO construction_history(development_id, role, company_name, company_url, first_seen) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(development_id, role, company_name) DO NOTHING",
                (dev_id, company.role, company.name, company.url, ts),
            )
        for m in page.milestones:
            self.conn.execute(
                "INSERT INTO construction_milestones(development_id, label, date_raw, date_parsed, first_seen) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(development_id, label) DO UPDATE SET "
                "date_raw=excluded.date_raw, date_parsed=excluded.date_parsed",
                (dev_id, m.label, m.date_raw, m.date_parsed, ts),
            )
        for u in page.timeline_updates:
            self.conn.execute(
                "INSERT OR IGNORE INTO construction_updates"
                "(development_id, area_id, date_raw, date_parsed, description, first_seen) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (dev_id, u.date_raw, u.date_parsed, u.description, ts),
            )
        for doc in page.documents:
            self._upsert_document(area_id=None, development_id=dev_id, doc=doc)

        self.conn.commit()
        return dev_id

    def upsert_development_stub(self, card, area_id: int | None, job_id: int | None = None) -> int:
        """Discovery-mode shortcut: create a lightweight development row directly
        from a /buildings listing card (name/url/raw_status — see
        models.BuildingLinkRef) WITHOUT fetching that development's own page. This
        is what makes discover mode genuinely cheaper than a full crawl (brief §25
        "broad first, deep second") rather than just a relabeling of the same work:
        the buildings-listing page already enumerates every development in an area,
        so there's no need to visit each one individually just to learn its name.

        Never downgrades an already-enriched row back to stub status.
        """
        ts = now()
        existing = self.conn.execute("SELECT id, is_stub FROM developments WHERE url=?", (card.url,)).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE developments SET last_seen=?, area_id=COALESCE(area_id, ?), "
                "raw_status=COALESCE(raw_status, ?) WHERE id=?",
                (ts, area_id, card.raw_status, existing["id"]),
            )
            self.conn.commit()
            return existing["id"]

        normalized = normalize_status(card.raw_status)
        slug = card.url.rstrip("/").rsplit("/", 1)[-1] if card.url else None
        cur = self.conn.execute(
            "INSERT INTO developments(url, slug, name, area_id, raw_status, normalized_status, "
            "is_active, is_stub, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
            (card.url, slug, card.name, area_id, card.raw_status, normalized, ts, ts),
        )
        dev_id = cur.lastrowid
        self._record_changes(job_id, "development", dev_id, card.url, None, {}, [])
        self.conn.commit()
        return dev_id

    def stub_development_urls(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Developments discovered (via a buildings listing) but never individually
        fetched — the enrich-mode work queue.
        """
        sql = "SELECT id, url FROM developments WHERE is_stub=1 AND is_active=1 ORDER BY id"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql).fetchall()

    def update_candidates(self, limit: int | None = None) -> list[sqlite3.Row]:
        """Already-enriched developments most likely to have changed, for update
        mode — under-construction/planned first, then longest-since-checked (brief
        §4 Mode 3, §25). Never re-checks a stub (it has nothing to compare against
        yet; that's enrich mode's job).
        """
        sql = """
            SELECT id, url FROM developments
            WHERE is_stub=0 AND is_active=1
            ORDER BY
                CASE normalized_status
                    WHEN 'under_construction' THEN 0
                    WHEN 'planned' THEN 1
                    WHEN 'announced' THEN 2
                    WHEN 'on_hold' THEN 3
                    ELSE 4
                END,
                last_seen ASC
        """
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql).fetchall()

    def _upsert_document(self, area_id: int | None, development_id: int | None, doc):
        ts = now()
        self.conn.execute(
            "INSERT INTO documents(development_id, area_id, doc_type, label, photo_count, url, "
            "photo_urls_json, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(development_id, area_id, doc_type) DO UPDATE SET "
            "photo_count=excluded.photo_count, label=excluded.label, "
            "photo_urls_json=excluded.photo_urls_json, last_seen=excluded.last_seen",
            (development_id, area_id, doc.doc_type, doc.label, doc.photo_count, doc.url,
             json.dumps(doc.photo_urls), ts, ts),
        )

    def get_development_by_url(self, url: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM developments WHERE url=?", (url,)).fetchone()

    def backfill_area_ids(self) -> int:
        """A development's `area_raw` (its immediate sub-community/district, e.g.
        "JVC District 11") often gets scraped before that district's own /dubai/{slug}
        area page has been crawled yet, so `area_id` is left NULL at insert time (see
        IMPLEMENTATION_STATUS.md). Re-resolving by name once more areas exist — cheap,
        idempotent, safe to call repeatedly (e.g. once per crawl run) — fixes this
        without needing to re-fetch every development page.
        """
        cur = self.conn.execute(
            "UPDATE developments SET area_id = ("
            "  SELECT a.id FROM areas a WHERE a.name = developments.area_raw"
            "     OR a.dld_community_name_en = developments.area_raw LIMIT 1"
            ") WHERE area_id IS NULL AND area_raw IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM areas a WHERE a.name = developments.area_raw "
            "            OR a.dld_community_name_en = developments.area_raw)"
        )
        self.conn.commit()
        return cur.rowcount

    def mark_missing_developments(self, seen_urls: set[str], area_id: int, job_id: int | None):
        """Compare the current /buildings listing against what's stored; flag any
        development previously seen for this area but absent from the latest listing
        as inactive ("page disappeared" per brief §16), without deleting history.
        """
        ts = now()
        rows = self.conn.execute(
            "SELECT id, url FROM developments WHERE area_id=? AND is_active=1", (area_id,)
        ).fetchall()
        for row in rows:
            if row["url"] not in seen_urls:
                self.conn.execute("UPDATE developments SET is_active=0, last_seen=last_seen WHERE id=?", (row["id"],))
                self.conn.execute(
                    "INSERT INTO change_log(entity_type, entity_id, entity_url, field_name, old_value, "
                    "new_value, detected_at, job_id, change_kind) VALUES ('development', ?, ?, 'is_active', '1', '0', ?, ?, 'disappeared')",
                    (row["id"], row["url"], ts, job_id),
                )
        self.conn.commit()

    # -- transactions -----------------------------------------------------

    def insert_transactions(self, records, development_id: int | None, area_id: int | None):
        ts = now()
        for t in records:
            self.conn.execute(
                "INSERT INTO transactions(transaction_id, development_id, area_id, transaction_date, "
                "transaction_date_raw, price_aed, price_per_sqft_aed, price_per_sqm_aed, size_sqft, room_type, "
                "property_type, property_subtype, property_use, registration_type, transaction_type, "
                "transaction_group, building_name_raw, project_raw, master_project_raw, area_raw, num_sellers, "
                "num_buyers, parking, source_url, first_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(transaction_id, source_url) DO NOTHING",
                (t.transaction_id, development_id, area_id, t.transaction_date, t.transaction_date_raw,
                 t.price_aed, t.price_per_sqft_aed, t.price_per_sqm_aed, t.size_sqft, t.room_type,
                 t.property_type, t.property_subtype, t.property_use, t.registration_type, t.transaction_type,
                 t.transaction_group, t.building_name_raw, t.project_raw, t.master_project_raw, t.area_raw,
                 t.num_sellers, t.num_buyers, t.parking, t.source_url, ts),
            )
        self.conn.commit()


def _safe_asdict(obj) -> dict:
    try:
        return asdict(obj)
    except Exception:
        return {}


def _norm_cmp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return str(value).strip()


def _str_or_none(value):
    return None if value is None else str(value)


def _merge_keep_existing(existing_row: sqlite3.Row, new_values: dict) -> dict:
    """Fill None values in `new_values` from the existing row so a partial re-scrape
    (e.g. an area's supporting sub-page lacking a field the main page has) never wipes
    out previously-captured data. Non-None new values always win (freshest wins).
    """
    merged = {}
    keys = existing_row.keys()
    for key, new_val in new_values.items():
        if new_val is None and key in keys and existing_row[key] is not None:
            merged[key] = existing_row[key]
        else:
            merged[key] = new_val
    return merged
