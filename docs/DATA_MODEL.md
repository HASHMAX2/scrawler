# Data Model

Warehouse: `data/warehouse.duckdb` (DuckDB). Built by `python scripts/refresh_data.py`, which calls
`ingestion.warehouse.build_warehouse()`. Source of truth for everything below is that module — this
doc explains the *why*, the code is the *what*.

## Layers

```
DATA FILES DLD\*.csv        raw source files, never modified
       |
  ingestion.staging          -> stg_dld_sales, stg_dld_rentals   (one row per source row, VARCHAR,
       |                                                          lineage: source_file/row_num/imported_at)
  ingestion.warehouse         -> dim_area, dim_project            (entity resolution)
       |                        fact_sales, fact_rentals          (typed, normalized, matched)
       v
  apps/api                    -> aggregation views/queries served to the frontend
```

Staging is append/replace-per-file (a changed file's old rows are deleted and reloaded; unchanged
files are skipped via `file_registry`'s content hash). `dim_area`, `dim_project`, `fact_sales`,
`fact_rentals` are **fully rebuilt from current staging contents on every run** — simpler and more
robust than incremental dimension merging at this row count (~1M rows total).

## Source files

| File(s) | Rows | Period | Notes |
|---|---|---|---|
| `transactions-*.csv` | 140,710 | 2026-01-01 → 2026-08-15 | `GROUP_EN` mixes Sales (106,327) / Mortgage (28,795) / Gifts (5,588) — analytics should filter `group_en='Sales'` |
| `rents-*.csv` (4 files) | 679,945 combined | 2026-01-01 → 2026-08-15 | Files are **contiguous date-range chunks, not duplicates** — they concatenate with zero row overlap |

## Entity resolution — the critical gap

**DLD's official community/project names barely overlap the scraper's Propsearch-sourced names.**
Only 13/267 DLD area names and 58/2,957 DLD project names matched scraped `areas.name` /
`developments.name` by exact string. Two consequences drove the design:

1. **DLD is the primary/canonical entity list, not the scraper.** `dim_area` and `dim_project`
   contain one row per distinct raw name seen in the DLD files — whether or not a scraped match
   exists — so a community the scraper hasn't reached yet still gets full sales/rental analytics.
   `fact_sales.area_id` / `fact_rentals.area_id` are **never NULL** as a result (verified: 0/140,710
   and 0/679,945 after a full load).

2. **The same community can appear under different DLD-native names in different source files.**
   Verified example: the transactions file uses `"JUMEIRAH VILLAGE CIRCLE"` for JVC; the rentals
   files use `"Al Barsha South Fourth"` (JVC's official DLD community name) for the *same place*.
   These land as two different `dim_area` rows. **Any community-level rollup must group by
   `dim_area.community_key`, not `dim_area.area_id`** — `community_key` collapses every dim_area row
   sharing the same `scraped_area_id` (when a scraped match exists) into one key
   (`"s{scraped_area_id}"`); areas with no scraped match get a standalone key (`"a{area_id}"`).

### Matching thresholds (`ingestion/entity_resolution.py`)

| confidence | meaning | linked automatically? |
|---|---|---|
| `exact` | normalized names equal | yes |
| `fuzzy_high` | rapidfuzz token_sort_ratio ≥ 90 | yes |
| `fuzzy_low` | score 75–89 | **no** — recorded as a suggestion for the Data Quality review UI |
| `unmatched` | score < 75 or no candidates | no |
| `scraped_only` (`dim_area` only) | a scraped area has no DLD-side name match at all | n/a (still a first-class row) |

Project matching tries a **building-level** match first (e.g. "Azizi Venice Tower 15"), falling back
to **development-level** (e.g. "Azizi Venice") — so both a whole master development and one specific
tower can be analyzed without the finer grain getting silently absorbed into the coarser one.

Confirmed manual corrections persist in `entity_alias_overrides (raw_key, entity_type, resolved_entity_id)`
and take priority over automatic matching on every subsequent rebuild.

### Current match coverage (informational — will improve as the scraper covers more of Dubai)

- Areas: 28 exact, 1 fuzzy_high, 40 fuzzy_low (awaiting review), 241 unmatched, 46 scraped-only.
- Projects: 60 exact, 43 fuzzy_high, 425 fuzzy_low (awaiting review), 2,698 unmatched.
- **Only ~3% of DLD projects currently have a confident scraped link** — developer attribution,
  construction status, and unit-mix enrichment are only available for that subset. This is a real,
  expected limitation (the scraper has crawled 185 of thousands of DLD-registered projects), not a
  bug — surfaced in the Data Quality page rather than hidden.

## Column-level notes

### `fact_sales` (from `transactions-*.csv`)
- `rooms_en` / `canonical_bedroom`: DLD's `ROOMS_EN` is populated for ~97% of Units and doubles as a
  property-type leak for non-residential rows (`"Hotel"`, `"Office"`, `"Shop"` appear here, not just
  bedroom counts) — these map to `canonical_bedroom = "Other"`, not a bedroom count.
- No developer column exists in the source at all. Developer attribution only works through
  `dim_project.matched_development_id → scraped.developments.developer_id`.
- `price_per_sqft_aed` is computed (`trans_value_aed / (area_sqm * 10.7639)`), not sourced directly.

### `fact_rentals` (from `rents-*.csv`)
- **`rooms` is 95.8% null overall and populated only for Villas (0% for Units/Flats).** Bedroom-level
  rental demand for apartments cannot come from this column — `canonical_bedroom_from_rentals()`
  falls back to `"Studio"` only when `PROP_SUB_TYPE_EN == "Studio"`, else `"Unknown"` for units with no
  room count. Do not present apartment bedroom splits as if they were reliable; label them clearly.
- 5,951 fully-duplicate raw rows were verified as **legitimate distinct contracts** (identical
  registration timestamp to the second — bulk-registered identical units in one batch), not export
  artifacts. They are kept, one `fact_rentals` row each.
- `annual_amount_aed` (not `contract_amount_aed`) is the right field for rent-level comparisons —
  the two differ on ~10.5% of rows (multi-month/multi-year contracts).

### Idempotency
`source_row_uid = "{dataset}:{source_file}:{row_num}"`, and each fact row's primary key is a
deterministic hash of that uid (`ingestion.warehouse._stable_id`). Re-running the pipeline on
unchanged files is a no-op (skipped by `file_registry`); re-running after a file changes reprocesses
only that file's staging rows, then rebuilds the (cheap, full-recompute) dimension/fact tables.

## Known gaps (documented, not silently patched)
- `unit_supply` (scraper-side) is currently empty — supply-vs-demand analytics will show "no supply
  data" rather than a fabricated number until the scraper populates it.
- No community boundary polygons exist anywhere in the data — map choropleth is not implemented.
