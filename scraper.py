#!/usr/bin/env python
"""Propsearch.ae Dubai real-estate scraper CLI.

Usage:
    python scraper.py https://propsearch.ae/dubai/jumeirah-village-circle
    python scraper.py https://propsearch.ae/dubai              # crawls all of Dubai

    python scraper.py <seed> --mode discover   # breadth-first: hierarchy + stub developments only
    python scraper.py       --mode enrich      # visit every stub development and extract full detail
    python scraper.py       --mode update      # re-check existing developments most likely to have changed
    python scraper.py --status                 # print entity/queue/budget report, no crawling

Give it ONE Propsearch URL. It discovers the relevant areas, sub-communities,
developments and buildings underneath that URL and stores everything in
data/propsearch.db (SQLite). Safe to interrupt (Ctrl+C) and re-run — crawl progress
is checkpointed in the `crawl_queue` table (brief §17). enrich/update modes need no
seed_url — they operate on what discover/full has already found.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from scraper.discovery import Crawler
from scraper.fetcher import Fetcher, FetcherConfig
from scraper.storage import Store
from scraper.url_utils import canonicalize

ROOT = Path(__file__).parent
DEFAULT_DB = ROOT / "data" / "propsearch.db"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"


def _normalize_seed(url: str) -> str:
    """The brief's example seed `https://propsearch.ae/dubai` 404s on the live site
    (see PROPSEARCH_STRUCTURE.md §1) — the real Dubai-wide area directory lives at
    /dubai/area-guides. Transparently redirect that one case; everything else (a
    specific area URL) is used as-is.
    """
    canon = canonicalize(url)
    if canon.rstrip("/") in ("https://propsearch.ae/dubai",):
        redirected = "https://propsearch.ae/dubai/area-guides"
        logging.getLogger("propsearch.cli").info(
            "[INFO] %s has no content on Propsearch; using the Dubai-wide directory instead: %s",
            canon, redirected,
        )
        return redirected
    return canon


def _print_status(store: Store) -> None:
    counts = store.entity_counts()
    requests_today = store.requests_used_today()
    running_jobs = store.conn.execute(
        "SELECT id, seed_url, status, started_at FROM crawl_jobs WHERE status IN ('running', 'paused') ORDER BY id DESC"
    ).fetchall()

    print()
    print("PROPSEARCH CRAWLER STATUS")
    print()
    if running_jobs:
        for j in running_jobs:
            qc = store.queue_counts(j["id"])
            print(f"Job #{j['id']}  [{j['status'].upper()}]  seed: {j['seed_url']}")
            print(f"  queue: {qc}")
    else:
        print("No running/paused jobs.")
    print()
    print("Entities")
    print(f"  Areas:                {counts['areas_total']:>6}  "
          f"(community: {counts['areas_community']}, landmark: {counts['areas_landmark']}, mall: {counts['areas_mall']})")
    print(f"  Sub-communities:      {counts['sub_communities']:>6}")
    print(f"  Developments:         {counts['developments_total']:>6}  "
          f"(enriched: {counts['developments_enriched']}, stub: {counts['developments_stub']})")
    print(f"  Buildings:            {counts['buildings']:>6}")
    print(f"  Developers:           {counts['developers']:>6}")
    print(f"  Schools:              {counts['schools']:>6}")
    print(f"  Amenities:            {counts['amenities']:>6}")
    print(f"  Mentioned places:     {counts['mentioned_places']:>6}")
    print(f"  Entity aliases:       {counts['entity_aliases']:>6}")
    print(f"  Transactions:         {counts['transactions']:>6}")
    print()
    print(f"Requests today (UTC):   {requests_today}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("seed_url", nargs="?", default=None,
                     help="A Propsearch.ae Dubai URL to start discovery from (required for --mode full/discover)")
    ap.add_argument("--mode", choices=["full", "discover", "enrich", "update"], default="full",
                     help="full (default): discover+extract in one pass, unchanged historical behavior. "
                          "discover: breadth-first only — creates stub developments without fetching each one. "
                          "enrich: fully extract every stub development created by a prior discover run. "
                          "update: re-check existing developments most likely to have changed "
                          "(under-construction/planned first). enrich/update need no seed_url.")
    ap.add_argument("--status", action="store_true", help="Print an entity/queue/budget status report and exit (no crawling)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path (default: data/propsearch.db)")
    ap.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR), help="Directory for raw HTML snapshots")
    ap.add_argument("--delay", type=float, default=1.5, help="Seconds to wait between requests (default: 1.5)")
    ap.add_argument("--concurrency", type=int, default=1,
                     help="Reserved for future use; the crawler is currently single-threaded by design "
                          "to keep the politeness policy simple and predictable (default: 1)")
    ap.add_argument("--max-pages", type=int, default=None,
                     help="Stop after processing this many pages in this run (default: unlimited)")
    ap.add_argument("--max-requests-per-day", type=int, default=None,
                     help="Stop once this many requests have been made today (UTC); resumable tomorrow (default: unlimited)")
    ap.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout in seconds")
    ap.add_argument("-v", "--verbose", action="store_true", help="Show debug-level logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx/httpcore/h2/hpack are extremely chatty at DEBUG (raw HTTP/2 frame dumps) —
    # keep our own [TAG]-style lines clean per brief §24 regardless of -v.
    for noisy in ("httpx", "httpcore", "hpack", "h2"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.status:
        # migrate=False: a status check is read-only and must not contend for the
        # SQLite write lock with a concurrently running crawl (see Store.__init__).
        with Store(args.db, migrate=False) as store:
            _print_status(store)
        return 0

    fetcher_config = FetcherConfig(delay_seconds=args.delay, timeout_seconds=args.timeout)
    with Store(args.db) as store, Fetcher(fetcher_config) as fetcher:
        crawler = Crawler(store, fetcher, Path(args.raw_dir), max_pages=args.max_pages,
                           mode=args.mode, max_requests_per_day=args.max_requests_per_day)

        if args.mode == "enrich":
            job_id = crawler.run_enrich(limit=args.max_pages)
            if job_id is None:
                print("Nothing to enrich — no stub developments found. Run with --mode discover first.")
                return 0
        elif args.mode == "update":
            job_id = crawler.run_update(limit=args.max_pages)
            if job_id is None:
                print("Nothing to update — no enriched developments found yet.")
                return 0
        else:
            if not args.seed_url:
                print(f"Error: seed_url is required for --mode {args.mode}", file=sys.stderr)
                return 1
            seed = _normalize_seed(args.seed_url)
            if "propsearch.ae" not in seed:
                print("Error: seed URL must be a propsearch.ae URL", file=sys.stderr)
                return 1
            job_id = crawler.run(seed)

        stats = store.job_stats(job_id)
        counts = store.queue_counts(job_id)
        requests_today = store.requests_used_today()

    print()
    print(f"Job #{job_id}: {stats.get('status')}  (mode: {args.mode})")
    print(f"  Pages discovered: {stats.get('pages_discovered')}")
    print(f"  Pages processed:  {stats.get('pages_processed')}")
    print(f"  Pages failed:     {stats.get('pages_failed')}")
    print(f"  Pages blocked:    {stats.get('pages_blocked')}")
    print(f"  Queue remaining:  {counts.get('pending', 0)} pending, {counts.get('failed', 0)} failed")
    print(f"  Requests today:   {requests_today}"
          + (f" / {args.max_requests_per_day}" if args.max_requests_per_day else ""))
    if counts.get("pending", 0) > 0:
        print()
        print("  Crawl not finished — re-run the same command to resume (checkpointed).")
    print()
    print("  Run `python dashboard.py` to explore the results, `python scraper.py --status` for a full report, "
          "or use scraper/exporter.py for CSV/JSON export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
