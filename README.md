# Propsearch Dubai Real-Estate Scraper

Give it one Propsearch.ae URL. It discovers the areas, sub-communities, developments
and buildings underneath that URL, scrapes what's publicly available, and stores it
in a local SQLite database you can browse in a dashboard or export to CSV/JSON.

See `PROPSEARCH_STRUCTURE.md` for how the site is actually structured (this was
written from live inspection, not assumptions), and `IMPLEMENTATION_STATUS.md` for
what's built, what's known-imperfect, and why specific design decisions were made.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

## Usage

Scrape one area and everything under it:

```bash
python scraper.py https://propsearch.ae/dubai/jumeirah-village-circle
```

Scrape all of Dubai (progressively — safe to stop and resume):

```bash
python scraper.py https://propsearch.ae/dubai
```

Useful flags:

```bash
python scraper.py <url> --max-pages 200   # stop after 200 pages this run
python scraper.py <url> --delay 2.0       # seconds between requests (default 1.5)
python scraper.py <url> -v                # verbose logging
```

The crawl is checkpointed in SQLite (`crawl_queue` table) — if it's interrupted
(Ctrl+C, crash, hitting `--max-pages`), just re-run the exact same command and it
picks up where it left off instead of starting over.

### Dashboard

```bash
python dashboard.py
```

Then open <http://localhost:8000>. Shows crawl progress, database totals, status
breakdowns, data-quality coverage, recently discovered/changed records, and
searchable/filterable area and development pages.

### Export

From the dashboard's Export page, or directly:

```bash
python -m scraper.exporter --db data/propsearch.db --out exports --format both --combined
```

Writes `areas.csv`, `developments.csv`, `buildings.csv`, `unit_supply.csv`,
`transactions.csv`, `amenities.csv`, `schools.csv` (+ JSON equivalents), plus one
nested `combined.json` with developments/buildings/transactions grouped under their
area.

### Tests

```bash
pytest tests/ -q
```

Parser tests run against real HTML fixtures saved under `tests/fixtures/` (fetched
from the live site during development — see PROPSEARCH_STRUCTURE.md), so extraction
logic is verified without hitting Propsearch on every test run.

## What gets scraped

- **Areas / communities**: name, parent, description, developer, DLD community stats,
  Propsearch's own development-status counts, sub-communities, transactions, amenities,
  schools.
- **Developments / buildings**: identity, location, status (raw + normalized), unit
  counts (never fabricated — missing stays `NULL`, not `0`), construction
  milestones/timeline, project value, developer/architect/contractor, coordinates,
  documents (masterplan/construction-photo gallery references), transactions. Where
  Propsearch explicitly describes a development as a multi-building complex, each
  named sub-building gets its own linked record — the tool does not assume
  1 development = 1 building.
- **Transactions**: DLD sale/mortgage records as published on area and development
  pages.

Everything not covered above (documented, and why) is in `IMPLEMENTATION_STATUS.md`.

## Project structure

```
scraper.py              CLI entry point
dashboard.py             Dashboard entry point
scraper/
    discovery.py          Crawl orchestration + checkpointing
    fetcher.py             httpx wrapper: retries, backoff, block detection
    parser.py               BeautifulSoup extraction (area/development/amenities/schools pages)
    normalizer.py            Status vocabulary, dates, numbers
    storage.py                SQLite schema, upsert/dedup, change tracking
    models.py                  Dataclasses shared between parser and storage
    url_utils.py                Canonicalization, allowlist
    exporter.py                  CSV/JSON export
dashboard/
    app.py                FastAPI routes
    queries.py             All dashboard numbers, computed live from SQLite
    templates/               Jinja2 templates
data/
    propsearch.db          SQLite database (created on first run)
    raw/                     Raw HTML snapshots, one file per unique page content hash
exports/                CSV/JSON output
tests/
    fixtures/             Real HTML samples used by parser tests
PROPSEARCH_STRUCTURE.md  Site structure findings (read this before touching parser.py)
IMPLEMENTATION_STATUS.md What's done, what's approximate, and why
```

## Notes

- Respectful by default: ~1.5s delay, single-threaded, retries with backoff, backs off
  further on the site's own `x-ratelimit-*` headers, and stops after repeated
  403/challenge responses rather than trying to push through.
- No CAPTCHA bypass, no anti-bot circumvention. A handful of secondary fields (a
  "Companies Directory" table with finer contractor roles, exact Parcel ID/Plot
  Reference) are served behind what appears to be a free-view/account gate for
  anonymous requests — those are simply left blank rather than worked around; see
  PROPSEARCH_STRUCTURE.md §4.
