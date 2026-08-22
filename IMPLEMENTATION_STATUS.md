# Implementation Status

Honest account of what's built, what's been validated against the live site, what's
approximate, and the reasoning behind non-obvious decisions. Read this alongside
`PROPSEARCH_STRUCTURE.md` (what the site actually looks like) before changing
`scraper/parser.py` or `scraper/discovery.py`.

## What's working, validated against the live site

- **Discovery**: seeding with a specific area (`/dubai/jumeirah-village-circle`)
  correctly discovers that area's page, its 4 supporting sub-pages
  (`/buildings`, `/amenities`, `/schools`, `/things-to-do`), its 14 sub-communities,
  and (from `/buildings`) all ~885 of JVC's development URLs. Seeding with
  `/dubai/area-guides` (or the bare `/dubai`, auto-redirected — see below) crawls all
  ~460+ Dubai areas via that index's `?page=N` pagination.
- **Extraction**: area pages, development/building pages (both single-building and
  multi-building-complex variants, plus sub-building pages that link back to their
  parent), the buildings-directory listing, amenities, and schools all parse
  correctly against real fixtures in `tests/fixtures/` — see `tests/test_parser.py`.
  The buildings-listing parser's status tally (`completed`/`under_construction`/
  `planned`/`cancelled` card counts, normalized) was cross-checked against
  Propsearch's own summary sentence on the same page and matches exactly
  (456/186+8/24+... /219 — see `test_parse_buildings_listing_status_breakdown_self_consistent`).
- **Storage/dedup/incremental updates**: re-running an upsert never duplicates a row
  (keyed on URL, not name); status/unit-count/developer changes are recorded in
  `change_log`; a development that disappears from its area's `/buildings` listing on
  a later crawl is marked `is_active=0` rather than deleted, with the transition
  logged. See `tests/test_storage.py`.
- **Dashboard**: overview, area detail, development detail, search/filter, CSV/JSON
  export all render against a real scraped database (manually verified during
  development against a partial JVC crawl).

## Bugs found and fixed during development (kept here so they don't get re-introduced)

1. **Block-detection false positive.** The naive block-page heuristic included a bare
   `"captcha"` substring marker. Propsearch embeds a normal, non-blocking Google
   reCAPTCHA Enterprise widget on every page, so every single fetch was being flagged
   as "blocked." Fixed by requiring more specific block-page phrases
   (`fetcher.py::_BLOCK_MARKERS`).
2. **Crawl-scope leakage via area-page prose.** Area guide pages contain content links
   to unrelated areas — e.g. "It takes roughly 21 minutes to drive to Dubai Mall...
   16 minutes to Palm Jumeirah" in the Transport & Access section — as real `<a
   href="/dubai/...">` links inside `<main>`. Blanket-following every in-content link
   turned a crawl seeded with just Jumeirah Village Circle into a crawl of Dubai
   Marina (26 sub-communities, +109 URLs), Palm Jumeirah (39 sub-communities, +74
   URLs), and beyond within minutes. Fixed with a `trusted_area_urls` set in
   `discovery.py::Crawler`: an area page only gets its outgoing links followed if it's
   the seed itself, one of the seed's (recursively) declared `subcommunities`, or the
   crawl is explicitly in full-Dubai mode. A tangentially-linked area still gets
   fetched and its own data stored (harmless, arguably useful), it just isn't treated
   as a fresh expansion point. Regression-tested in `tests/test_discovery.py` with a
   fake fetcher (no live requests) — the same bug reappearing wouldn't be caught by
   the fixture-based parser tests alone, which is why this second, narrower test file
   exists.
3. **SQLite commit-per-row was the dominant cost, not parsing or network.** The
   original `enqueue()` called `conn.commit()` twice per discovered link. A single
   JVC `/buildings` page discovers ~700-900 new URLs; at 2 commits/link with SQLite's
   default rollback-journal fsync-per-commit, that page alone took minutes. Fixed by
   (a) `enqueue_many()` — one `executemany` + one commit per page instead of ~1800
   commits, and (b) `PRAGMA journal_mode=WAL` / `synchronous=NORMAL` on the connection.
   Net effect: the same page went from ~2.5 minutes to a few seconds.
4. **Redundant re-parsing of the same HTML.** `parse_buildings_listing()` re-ran
   `BeautifulSoup(html, "lxml")` internally, and its call into `parse_area_page()` did
   so *again* — three full parses of a ~2MB document per page. `parser.py`'s
   `parse_area_page`/`parse_development_page`/`parse_buildings_listing`/
   `parse_amenities_page`/`parse_schools_page` now all accept an optional pre-parsed
   `soup`, and `discovery.py` threads the one parse it already did (for
   classification) through to whichever extractor runs next.
5. **`data-sqft`/`data-orig` attributes contain comma-formatted numbers** (e.g.
   `"1,611"`), which `float()` rejects outright — transaction size/price parsing was
   crashing on any transaction over 999 sqft or AED 999. Fixed by stripping commas
   before the numeric conversion (`parser.py::parse_transactions`).
6. **`area_id` resolution is order-dependent and was silently failing for ~30% of
   developments in real crawls.** A development's `area_raw` ("JVC District 11") is
   only resolvable to a stored `areas.id` if that district's own guide page has
   already been scraped — but the crawl queue is FIFO, and about a third of
   development pages in a real JVC run were processed before their district area page
   was. Once `area_id` was written as `NULL` at insert time, it stayed `NULL` forever
   (no re-resolution on later runs unless that exact development URL got re-fetched).
   Fixed with `Store.backfill_area_ids()`, a cheap idempotent `UPDATE ... WHERE
   area_id IS NULL` re-resolution pass run once at the end of every `Crawler.run()`.
7. **Area-detail dashboard numbers were near-zero for top-level areas.** Propsearch
   tags a development's `Area` field at the *district* level (e.g. "JVC District 11"),
   never at the top-level community name ("Jumeirah Village Circle") — so even with
   bug #6 fixed, a naive `WHERE area_id = ?` against Jumeirah Village Circle's own row
   found 0 of its 32 real developments, because every one of them is actually tagged
   to one of its 9 districts. This directly contradicted the brief's own worked
   example (§19: "JUMEIRAH VILLAGE CIRCLE / Developments: 886"). Fixed with
   `dashboard/queries.py::rollup_area_ids` — a parent→children walk over `areas.
   parent_area_name` (the only hierarchy signal Propsearch's pages actually expose;
   there's no dedicated parent-id field) — used by every area-scoped dashboard query
   (`status_breakdown`, `data_quality`, `area_unit_coverage`, `list_areas`,
   `list_developments`). Regression-tested in `tests/test_queries.py`.

## Known limitations / deliberately out of scope

- **A "Companies Directory" table (finer contractor roles: Piling Contractor, MEP
  Consultant, etc.) and exact Parcel ID / Plot Reference values are gated** behind
  what appears to be a free-view-limit or account wall for anonymous HTTP requests —
  confirmed by comparing a plain `curl` fetch (shows generic "N Companies Involved" /
  lock icons, no real data) against the same page in an authenticated-looking browser
  session (shows real names/links). Per the brief's explicit prohibition on
  CAPTCHA/anti-bot circumvention, this is not worked around. The `developer`,
  `architect`, and `contractor` (building + foundation) are still captured, because
  those specific fields *are* present in the plain-HTTP response as free text under
  BUILDING SPECIFICATIONS — see `parser.py::companies_from_specs` and
  `PROPSEARCH_STRUCTURE.md` §4.
- **No price-history chart data.** The brief's source material mentions "price history
  charts" on building pages; no embedded chart JSON or extra XHR was found during live
  inspection (only ~1.3KB of inline `<script>` content, none of it chart data). Not
  built, because building against unconfirmed markup was explicitly against the
  brief's instructions. If Propsearch renders these charts via a mechanism not
  exercised during this investigation (e.g. only on scroll-into-view), it would need
  re-inspecting network traffic while interacting with that widget specifically.
- **Bedroom-level unit breakdown (studio/1BR/2BR/.../5BR+) was never observed** on any
  building page during inspection — only a single free-text "total units" sentence.
  Per the brief ("never treat missing data as zero"), those `unit_supply` columns
  exist in the schema but are only ever populated if a future page inspection finds
  where Propsearch actually publishes that breakdown; right now they stay `NULL` for
  every record, which is correct given what's observed, not a bug.
- **Buildings vs. developments modeling**: Propsearch's own building-guide pages
  conflate "development" and "building" into one page template. This scraper treats a
  record as a `development` unless it's explicitly named as a sub-building by a
  parent (`Sub-buildings` field on a multi-building-complex page, e.g. Cello → Cello
  Block A/B) — in which case it also gets a row in `buildings`, linked to the parent
  `development`. The common case (one page = one physical building, no complex) is
  *not* duplicated into both tables — the `developments` row *is* that building. This
  matches the brief's "don't assume 1:1, but don't fabricate structure either."
- **Developer/contractor profile pages are not crawled**, by design — see
  `url_utils.py`'s comment on `ALLOWED_PATH_PREFIXES`. A developer like Nakheel has
  projects across all of Dubai; following its profile page's project list from an
  area-scoped crawl would reintroduce the same scope-leakage problem fixed above.
  Developer name + URL is still captured (from each development's own page), just
  never used as a crawl seed.
- **Live property listings** (`/dubai-properties-for-sale/...`, `/dubai-properties-to-rent/...`)
  are intentionally not scraped — the brief frames this project around development/
  building records, not live unit listings (explicitly contrasted with "generic
  Bayut/Property Finder scrapers" in the brief's "do not build" list). Listing *counts*
  shown on area/development pages ("Studios (65)") are visible in the HTML but not
  currently extracted into a table; they're a snapshot of live market activity, not a
  development record, and were left out to keep scope aligned with the brief's stated
  priority.
- **The `/buildings` directory listing was observed unpaginated** for Jumeirah Village
  Circle (all ~886 developments in one ~2MB response). The parser/crawler doesn't
  assume this holds for every area of every size — `parser.classify_page` and the
  card-scan approach work regardless of page size — but pagination handling for this
  specific page type has not been exercised against a real paginated example, because
  none was found during inspection.
- **Rate-limit headers**: live responses were observed carrying `x-ratelimit-limit`
  and `x-ratelimit-remaining` headers (values seen around 45/window). The fetcher
  proactively pauses when remaining capacity gets low (`fetcher.py::
  _respect_rate_limit_headers`), on top of the configurable fixed delay — this
  wasn't in the original spec but is a direct, low-risk application of a signal the
  site itself provides for being polite.

## Design decisions worth knowing about

- **Single-threaded crawler.** The brief asks for "low concurrency," and a single
  worker with a fixed delay is the simplest thing that satisfies that — no thread
  pool, no async event loop, no work-stealing queue. `--concurrency` exists as a flag
  for forward-compatibility but is currently a no-op; scaling past 1 worker would need
  the SQLite access pattern revisited (WAL mode helps, but `crawl_queue` claiming
  would need a proper `SELECT ... FOR UPDATE`-equivalent, which SQLite doesn't have).
- **Raw HTML is deduplicated by content hash on disk** (`data/raw/{hash[:16]}.html`),
  not one file per URL-visit — re-scraping an unchanged page doesn't grow the raw
  archive. `scraped_pages` keeps the URL→hash mapping so a specific visit's raw HTML
  can always be found again for re-parsing.
- **SQLite, no ORM.** Given the modest schema size and the brief's "don't
  over-engineer" instruction, hand-written SQL in `storage.py` was chosen over
  SQLAlchemy — fewer moving parts, and the upsert/dedup/change-log logic needed
  row-level control that an ORM would mostly get in the way of.
