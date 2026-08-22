"""DuckDB warehouse: DDL + orchestration that (re)builds dim_area, dim_project,
fact_sales and fact_rentals from whatever is currently in the staging tables
plus the scraper's SQLite data (attached read-only).

Staging tables are maintained incrementally (per-file, via ingestion.staging +
file_registry hash checks — unchanged files are never reprocessed). The
dimension and fact tables built here, however, are fully recomputed from
current staging contents on every call: with only ~270 areas / ~3,000
projects / <1M fact rows this is cheap, and a full rebuild is simpler and
more robust than incremental dimension merging (no stale-row bookkeeping,
entity_alias_overrides are re-applied fresh every time).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pandas as pd

from ingestion.entity_resolution import (
    build_area_candidates,
    build_project_candidates,
    match_name,
    resolve_project,
)
from ingestion.normalize import (
    canonical_bedroom_from_rentals,
    canonical_bedroom_from_rooms_en,
    canonical_key,
    canonical_property_type,
    parse_dld_date,
)
from ingestion.project_hierarchy import display_name_from_key, extract_building_suffix, slugify

SCRAPED_DB_DEFAULT = Path("data/propsearch.db")

DDL = """
CREATE TABLE IF NOT EXISTS entity_alias_overrides (
    raw_key VARCHAR NOT NULL,
    entity_type VARCHAR NOT NULL,      -- 'area' | 'project'
    resolved_entity_id INTEGER,        -- NULL means "confirmed unmatched"
    resolved_by VARCHAR NOT NULL DEFAULT 'user',
    resolved_at TIMESTAMP NOT NULL DEFAULT now(),
    note VARCHAR,
    PRIMARY KEY (raw_key, entity_type)
);

CREATE TABLE IF NOT EXISTS master_project_overrides (
    raw_project_canonical_key VARCHAR PRIMARY KEY,
    override_master_key VARCHAR NOT NULL,
    resolved_by VARCHAR NOT NULL DEFAULT 'user',
    resolved_at TIMESTAMP NOT NULL DEFAULT now(),
    note VARCHAR
);
"""


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)


def attach_scraped_db(con: duckdb.DuckDBPyConnection, db_path: Path = SCRAPED_DB_DEFAULT) -> None:
    con.execute("INSTALL sqlite; LOAD sqlite;")
    attached = con.execute("SELECT database_name FROM duckdb_databases()").fetchall()
    if any(name == "scraped" for (name,) in attached):
        return
    con.execute(f"ATTACH '{db_path.as_posix()}' AS scraped (TYPE sqlite, READ_ONLY)")


def _load_overrides(con: duckdb.DuckDBPyConnection, entity_type: str) -> dict[str, int]:
    rows = con.execute(
        "SELECT raw_key, resolved_entity_id FROM entity_alias_overrides WHERE entity_type = ? AND resolved_entity_id IS NOT NULL",
        [entity_type],
    ).fetchall()
    return {raw_key: entity_id for raw_key, entity_id in rows}


def build_dim_area(con: duckdb.DuckDBPyConnection) -> int:
    scraped_areas = con.execute(
        "SELECT id, name, also_known_as, dld_community_name_en FROM scraped.areas"
    ).fetchall()
    scraped_areas = [
        {"id": r[0], "name": r[1], "also_known_as": r[2], "dld_community_name_en": r[3]}
        for r in scraped_areas
    ]
    scraped_subs = con.execute("SELECT id, parent_area_id, name FROM scraped.sub_communities").fetchall()
    scraped_subs = [{"id": r[0], "parent_area_id": r[1], "name": r[2]} for r in scraped_subs]

    candidates = build_area_candidates(scraped_areas, scraped_subs)
    overrides = _load_overrides(con, "area")
    scraped_name_by_id = {a["id"]: a["name"] for a in scraped_areas}

    dld_names = con.execute("""
        SELECT DISTINCT "AREA_EN" FROM stg_dld_sales WHERE "AREA_EN" IS NOT NULL
        UNION
        SELECT DISTINCT "AREA_EN" FROM stg_dld_rentals WHERE "AREA_EN" IS NOT NULL
    """).fetchall()

    rows = []
    seen_keys: set[str] = set()
    next_id = 1
    for (raw_name,) in dld_names:
        key = canonical_key(raw_name)
        if key in seen_keys:
            # Two raw DLD names differing only in case/punctuation (e.g.
            # "Palm Deira" vs "PALM DEIRA") canonicalize to the same key —
            # this must collapse to one dim_area row, not two, or fact rows
            # for the "same" area split across two area_ids and every
            # community-level rollup undercounts.
            continue
        seen_keys.add(key)
        result = match_name(key, candidates, overrides)
        rows.append((next_id, raw_name, key, result.matched_id, result.confidence, result.score))
        next_id += 1
    for area in scraped_areas:
        key = canonical_key(area["name"])
        if key in seen_keys:
            continue
        rows.append((next_id, None, key, area["id"], "scraped_only", 100.0))
        seen_keys.add(key)
        next_id += 1

    # community_key/community_name: the rollup grain for community-level
    # analytics. Different DLD source files use DIFFERENT official names for
    # the same physical community (verified: sales use "JUMEIRAH VILLAGE
    # CIRCLE", rentals use "Al Barsha South Fourth" for the same place) — so
    # sales and rentals for one community can land on different dim_area
    # rows. When a scraped match exists, every dim_area row sharing that
    # scraped_area_id collapses to one community_key ("s{scraped_area_id}")
    # so sales+rentals combine correctly; areas with no scraped match get a
    # standalone community_key ("a{area_id}") and keep their own raw name as
    # the display name.
    final_rows = []
    for area_id, raw_name, key, scraped_area_id, confidence, score in rows:
        if scraped_area_id is not None and confidence != "scraped_only":
            community_key = f"s{scraped_area_id}"
            community_name = scraped_name_by_id.get(scraped_area_id, raw_name)
        elif confidence == "scraped_only":
            community_key = f"s{scraped_area_id}"
            community_name = scraped_name_by_id.get(scraped_area_id, raw_name)
        else:
            community_key = f"a{area_id}"
            community_name = raw_name
        final_rows.append((area_id, raw_name, key, scraped_area_id, confidence, score, community_key, community_name))

    con.execute("""
        CREATE OR REPLACE TABLE dim_area (
            area_id INTEGER PRIMARY KEY,
            dld_area_name VARCHAR,
            canonical_key VARCHAR NOT NULL,
            scraped_area_id INTEGER,
            match_confidence VARCHAR NOT NULL,
            match_score DOUBLE NOT NULL,
            community_key VARCHAR NOT NULL,
            community_name VARCHAR NOT NULL
        )
    """)
    con.executemany("INSERT INTO dim_area VALUES (?, ?, ?, ?, ?, ?, ?, ?)", final_rows)
    return len(final_rows)


def build_dim_project(con: duckdb.DuckDBPyConnection) -> int:
    scraped_devs = con.execute("SELECT id, name FROM scraped.developments").fetchall()
    scraped_devs = [{"id": r[0], "name": r[1]} for r in scraped_devs]
    scraped_bldgs = con.execute("SELECT id, development_id, name FROM scraped.buildings").fetchall()
    scraped_bldgs = [{"id": r[0], "development_id": r[1], "name": r[2]} for r in scraped_bldgs]

    dev_candidates, building_candidates = build_project_candidates(scraped_devs, scraped_bldgs)
    overrides = _load_overrides(con, "project")

    dld_names = con.execute("""
        SELECT "PROJECT_EN", "MASTER_PROJECT_EN" FROM stg_dld_sales WHERE "PROJECT_EN" IS NOT NULL
        UNION
        SELECT "PROJECT_EN", "MASTER_PROJECT_EN" FROM stg_dld_rentals WHERE "PROJECT_EN" IS NOT NULL
    """).fetchall()

    rows = []
    seen_keys: set[str] = set()
    for project_id, (raw_name, master_name) in enumerate(dld_names, start=1):
        key = canonical_key(raw_name)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        result, building_id = resolve_project(key, dev_candidates, building_candidates, overrides)
        if result.matched_id is None and master_name:
            master_key = canonical_key(master_name)
            master_result, _ = resolve_project(master_key, dev_candidates, building_candidates, overrides)
            if master_result.matched_id is not None:
                result = master_result
        rows.append((project_id, raw_name, master_name, key, result.matched_id, building_id, result.confidence, result.score))

    con.execute("""
        CREATE OR REPLACE TABLE dim_project (
            project_id INTEGER PRIMARY KEY,
            dld_project_name VARCHAR,
            dld_master_project_name VARCHAR,
            canonical_key VARCHAR NOT NULL,
            matched_development_id INTEGER,
            matched_building_id INTEGER,
            match_confidence VARCHAR NOT NULL,
            match_score DOUBLE NOT NULL
        )
    """)
    con.executemany("INSERT INTO dim_project VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def build_dim_project_hierarchy(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Groups dim_project rows (already building-grain, e.g. "AZIZI VENICE
    14") into persisted master-project families using the deterministic
    rules in ingestion.project_hierarchy — never fuzzy matching, so a
    grouping is always defensible. Manual corrections in
    master_project_overrides (keyed by the BUILDING's own canonical_key) are
    applied before grouping, so an admin can move a mis-grouped building into
    a different family, or force a standalone project to split out on its
    own by overriding it to its own canonical_key.

    Populates dim_master_project (the parent entity) and adds
    master_project_id/building_label/building_slug/grouping_method onto
    dim_project. developer_name/area_name on dim_master_project are left
    NULL here and filled by enrich_dim_master_project() once fact tables
    exist to aggregate from.
    """
    rows = con.execute(
        "SELECT project_id, dld_project_name, canonical_key FROM dim_project WHERE dld_project_name IS NOT NULL"
    ).fetchall()
    overrides = dict(
        con.execute("SELECT raw_project_canonical_key, override_master_key FROM master_project_overrides").fetchall()
    )

    building_rows = []  # (project_id, raw_name, master_key, building_label, method)
    for project_id, raw_name, proj_key in rows:
        natural = extract_building_suffix(raw_name)
        if proj_key in overrides:
            building_rows.append((project_id, raw_name, overrides[proj_key], natural.building_label, "manual_override"))
        else:
            building_rows.append((project_id, raw_name, natural.master_key, natural.building_label, natural.method))

    groups: dict[str, list[tuple]] = {}
    for row in building_rows:
        groups.setdefault(row[2], []).append(row)

    master_rows = []
    project_updates = []  # (project_id, master_project_id, building_label, building_slug, grouping_method)
    used_building_slugs: set[str] = set()
    for master_id, master_key in enumerate(sorted(groups.keys()), start=1):
        members = groups[master_key]
        building_count = len(members)
        needs_review = any(m[4] in ("hyphen_split", "manual_override") for m in members)
        display_name = members[0][1].strip() if building_count == 1 else display_name_from_key(master_key)
        slug = slugify(master_key)
        master_rows.append((master_id, master_key, display_name, slug, building_count, needs_review, None, None))

        for project_id, raw_name, _mk, building_label, method in members:
            base_slug = slugify(canonical_key(raw_name)) if raw_name else f"project-{project_id}"
            b_slug = base_slug
            n = 2
            while b_slug in used_building_slugs:
                b_slug = f"{base_slug}-{n}"
                n += 1
            used_building_slugs.add(b_slug)
            project_updates.append((project_id, master_id, building_label, b_slug, method))

    con.execute("""
        CREATE OR REPLACE TABLE dim_master_project (
            master_project_id INTEGER PRIMARY KEY,
            canonical_key VARCHAR NOT NULL UNIQUE,
            display_name VARCHAR NOT NULL,
            slug VARCHAR NOT NULL UNIQUE,
            building_count INTEGER NOT NULL,
            needs_review BOOLEAN NOT NULL,
            developer_name VARCHAR,
            area_name VARCHAR
        )
    """)
    con.executemany("INSERT INTO dim_master_project VALUES (?, ?, ?, ?, ?, ?, ?, ?)", master_rows)

    con.execute("ALTER TABLE dim_project ADD COLUMN IF NOT EXISTS master_project_id INTEGER")
    con.execute("ALTER TABLE dim_project ADD COLUMN IF NOT EXISTS building_label VARCHAR")
    con.execute("ALTER TABLE dim_project ADD COLUMN IF NOT EXISTS building_slug VARCHAR")
    con.execute("ALTER TABLE dim_project ADD COLUMN IF NOT EXISTS grouping_method VARCHAR")

    updates_df = pd.DataFrame(
        project_updates, columns=["project_id", "master_project_id", "building_label", "building_slug", "grouping_method"]
    )
    con.register("_hierarchy_updates", updates_df)
    con.execute("""
        UPDATE dim_project
        SET master_project_id = u.master_project_id,
            building_label = u.building_label,
            building_slug = u.building_slug,
            grouping_method = u.grouping_method
        FROM _hierarchy_updates u
        WHERE dim_project.project_id = u.project_id
    """)
    con.unregister("_hierarchy_updates")

    return {"dim_master_project": len(master_rows), "dim_project_linked": len(project_updates)}


def enrich_dim_master_project(con: duckdb.DuckDBPyConnection) -> None:
    """Fills dim_master_project.developer_name/area_name by mode() across
    each family's fact rows, joined through the now-built fact tables. Runs
    after build_fact_sales/build_fact_rentals since it needs area_id
    resolution already done on the fact rows.
    """
    dev_rows = con.execute("""
        SELECT dp.master_project_id, mode(dev.name)
        FROM dim_project dp
        JOIN scraped.developments d ON dp.matched_development_id = d.id
        JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE dp.master_project_id IS NOT NULL
        GROUP BY 1
    """).fetchall()

    area_rental_rows = con.execute("""
        SELECT dp.master_project_id, mode(da.community_name)
        FROM fact_rentals fr
        JOIN dim_project dp ON fr.project_id = dp.project_id
        JOIN dim_area da ON fr.area_id = da.area_id
        WHERE dp.master_project_id IS NOT NULL
        GROUP BY 1
    """).fetchall()
    area_sales_rows = con.execute("""
        SELECT dp.master_project_id, mode(da.community_name)
        FROM fact_sales fs
        JOIN dim_project dp ON fs.project_id = dp.project_id
        JOIN dim_area da ON fs.area_id = da.area_id
        WHERE dp.master_project_id IS NOT NULL
        GROUP BY 1
    """).fetchall()
    area_map = dict(area_rental_rows)
    area_map.update(dict(area_sales_rows))  # prefer the sales-side area tag when both exist
    dev_map = dict(dev_rows)

    all_ids = sorted(set(dev_map) | set(area_map))
    if not all_ids:
        return
    enrich_df = pd.DataFrame(
        {"master_project_id": all_ids, "developer_name": [dev_map.get(i) for i in all_ids], "area_name": [area_map.get(i) for i in all_ids]}
    )
    con.register("_master_enrich", enrich_df)
    con.execute("""
        UPDATE dim_master_project
        SET developer_name = e.developer_name, area_name = e.area_name
        FROM _master_enrich e
        WHERE dim_master_project.master_project_id = e.master_project_id
    """)
    con.unregister("_master_enrich")


def _stable_id(row_uid: str) -> int:
    """Deterministic BIGINT id from a row_uid: same source row always gets
    the same fact-table primary key across rebuilds, without needing a
    running sequence. 15 hex digits (60 bits) comfortably fits BIGINT.
    """
    return int(hashlib.sha1(row_uid.encode("utf-8")).hexdigest()[:15], 16)


def build_fact_sales(con: duckdb.DuckDBPyConnection) -> int:
    raw = con.execute("""
        SELECT source_file, row_num, "TRANSACTION_NUMBER", "INSTANCE_DATE", "GROUP_EN", "PROCEDURE_EN",
               "IS_OFFPLAN_EN", "IS_FREE_HOLD_EN", "USAGE_EN", "AREA_EN", "PROP_TYPE_EN", "PROP_SB_TYPE_EN",
               "TRANS_VALUE", "PROCEDURE_AREA", "ACTUAL_AREA", "ROOMS_EN", "PARKING",
               "NEAREST_METRO_EN", "NEAREST_MALL_EN", "NEAREST_LANDMARK_EN", "PROJECT_EN", imported_at
        FROM stg_dld_sales
    """).fetchall()
    cols = [d[0] for d in con.description]

    area_key_to_id = {r[2]: r[0] for r in con.execute("SELECT area_id, dld_area_name, canonical_key FROM dim_area").fetchall()}
    project_key_to_id = {r[2]: r[0] for r in con.execute("SELECT project_id, dld_project_name, canonical_key FROM dim_project").fetchall()}

    out = []
    for row in raw:
        d = dict(zip(cols, row))
        area_id = area_key_to_id.get(canonical_key(d["AREA_EN"]))
        project_id = project_key_to_id.get(canonical_key(d["PROJECT_EN"])) if d["PROJECT_EN"] else None
        row_uid = f"dld_sales:{d['source_file']}:{d['row_num']}"
        try:
            trans_value = float(d["TRANS_VALUE"]) if d["TRANS_VALUE"] not in (None, "") else None
        except ValueError:
            trans_value = None
        try:
            area_sqm = float(d["ACTUAL_AREA"]) if d["ACTUAL_AREA"] not in (None, "") else None
        except ValueError:
            area_sqm = None
        sqft = area_sqm * 10.7639 if area_sqm else None
        psf = (trans_value / sqft) if (trans_value and sqft) else None
        out.append((
            row_uid,
            parse_dld_date(d["INSTANCE_DATE"]),
            d["GROUP_EN"], d["PROCEDURE_EN"],
            d["IS_OFFPLAN_EN"] == "Off-Plan",
            d["IS_FREE_HOLD_EN"] == "Free Hold",
            d["USAGE_EN"],
            area_id, project_id,
            d["PROP_TYPE_EN"], d["PROP_SB_TYPE_EN"],
            canonical_property_type(d["PROP_SB_TYPE_EN"], d["PROP_TYPE_EN"]),
            d["ROOMS_EN"], canonical_bedroom_from_rooms_en(d["ROOMS_EN"]) or "Unknown",
            trans_value, area_sqm, psf,
            d["PARKING"], d["NEAREST_METRO_EN"], d["NEAREST_MALL_EN"], d["NEAREST_LANDMARK_EN"],
            d["source_file"], d["imported_at"],
        ))

    columns = [
        "source_row_uid", "instance_date", "group_en", "procedure_en", "is_offplan", "is_freehold",
        "usage_en", "area_id", "project_id", "prop_type_en", "prop_sub_type_en", "canonical_property_type",
        "rooms_en", "canonical_bedroom", "trans_value_aed", "area_sqm", "price_per_sqft_aed", "parking",
        "nearest_metro", "nearest_mall", "nearest_landmark", "source_file", "imported_at",
    ]
    df = pd.DataFrame(out, columns=columns)
    df.insert(0, "sale_id", [_stable_id(u) for u in df["source_row_uid"]])

    con.execute("""
        CREATE OR REPLACE TABLE fact_sales (
            sale_id BIGINT PRIMARY KEY,
            source_row_uid VARCHAR UNIQUE,
            instance_date DATE,
            group_en VARCHAR,
            procedure_en VARCHAR,
            is_offplan BOOLEAN,
            is_freehold BOOLEAN,
            usage_en VARCHAR,
            area_id INTEGER,
            project_id INTEGER,
            prop_type_en VARCHAR,
            prop_sub_type_en VARCHAR,
            canonical_property_type VARCHAR,
            rooms_en VARCHAR,
            canonical_bedroom VARCHAR,
            trans_value_aed DOUBLE,
            area_sqm DOUBLE,
            price_per_sqft_aed DOUBLE,
            parking VARCHAR,
            nearest_metro VARCHAR,
            nearest_mall VARCHAR,
            nearest_landmark VARCHAR,
            source_file VARCHAR,
            imported_at TIMESTAMP
        )
    """)
    # A single columnar INSERT ... SELECT FROM a registered DataFrame is
    # vectorized in DuckDB; executemany() over hundreds of thousands of rows
    # does a Python round trip per row and was ~1000x slower in practice.
    con.register("_fact_sales_stage", df)
    con.execute(f"""
        INSERT INTO fact_sales
        SELECT sale_id, source_row_uid, CAST(instance_date AS DATE), group_en, procedure_en,
               is_offplan, is_freehold, usage_en, area_id, project_id, prop_type_en, prop_sub_type_en,
               canonical_property_type, rooms_en, canonical_bedroom, trans_value_aed, area_sqm,
               price_per_sqft_aed, parking, nearest_metro, nearest_mall, nearest_landmark,
               source_file, imported_at
        FROM _fact_sales_stage
    """)
    con.unregister("_fact_sales_stage")
    return len(out)


def build_fact_rentals(con: duckdb.DuckDBPyConnection) -> int:
    raw = con.execute("""
        SELECT source_file, row_num, "REGISTRATION_DATE", "START_DATE", "END_DATE", "VERSION_EN",
               "AREA_EN", "CONTRACT_AMOUNT", "ANNUAL_AMOUNT", "IS_FREE_HOLD_EN", "ACTUAL_AREA",
               "PROP_TYPE_EN", "PROP_SUB_TYPE_EN", "ROOMS", "USAGE_EN", "NEAREST_METRO_EN",
               "NEAREST_MALL_EN", "NEAREST_LANDMARK_EN", "PARKING", "TOTAL_PROPERTIES", "PROJECT_EN", imported_at
        FROM stg_dld_rentals
    """).fetchall()
    cols = [d[0] for d in con.description]

    area_key_to_id = {r[2]: r[0] for r in con.execute("SELECT area_id, dld_area_name, canonical_key FROM dim_area").fetchall()}
    project_key_to_id = {r[2]: r[0] for r in con.execute("SELECT project_id, dld_project_name, canonical_key FROM dim_project").fetchall()}

    out = []
    for row in raw:
        d = dict(zip(cols, row))
        area_id = area_key_to_id.get(canonical_key(d["AREA_EN"]))
        project_id = project_key_to_id.get(canonical_key(d["PROJECT_EN"])) if d["PROJECT_EN"] else None
        row_uid = f"dld_rentals:{d['source_file']}:{d['row_num']}"

        def _f(x):
            try:
                return float(x) if x not in (None, "") else None
            except ValueError:
                return None

        annual = _f(d["ANNUAL_AMOUNT"])
        contract = _f(d["CONTRACT_AMOUNT"])
        area_sqm = _f(d["ACTUAL_AREA"])
        sqft = area_sqm * 10.7639 if area_sqm else None
        rent_psf = (annual / sqft) if (annual and sqft) else None
        rooms = _f(d["ROOMS"])

        out.append((
            row_uid,
            parse_dld_date(d["REGISTRATION_DATE"]), parse_dld_date(d["START_DATE"]), parse_dld_date(d["END_DATE"]),
            d["VERSION_EN"], d["VERSION_EN"] == "Renewed",
            area_id, project_id,
            d["PROP_TYPE_EN"], d["PROP_SUB_TYPE_EN"],
            canonical_property_type(d["PROP_SUB_TYPE_EN"], d["PROP_TYPE_EN"]),
            rooms, canonical_bedroom_from_rentals(rooms, d["PROP_SUB_TYPE_EN"], d["PROP_TYPE_EN"]),
            contract, annual, area_sqm, rent_psf,
            d["IS_FREE_HOLD_EN"] == "Free Hold", d["USAGE_EN"],
            _f(d["PARKING"]), int(_f(d["TOTAL_PROPERTIES"]) or 0),
            d["NEAREST_METRO_EN"], d["NEAREST_MALL_EN"], d["NEAREST_LANDMARK_EN"],
            d["source_file"], d["imported_at"],
        ))

    columns = [
        "source_row_uid", "registration_date", "start_date", "end_date", "version_en", "is_renewal",
        "area_id", "project_id", "prop_type_en", "prop_sub_type_en", "canonical_property_type",
        "rooms", "canonical_bedroom", "contract_amount_aed", "annual_amount_aed", "area_sqm",
        "rent_per_sqft_aed", "is_freehold", "usage_en", "parking", "total_properties",
        "nearest_metro", "nearest_mall", "nearest_landmark", "source_file", "imported_at",
    ]
    df = pd.DataFrame(out, columns=columns)
    df.insert(0, "rental_id", [_stable_id(u) for u in df["source_row_uid"]])

    con.execute("""
        CREATE OR REPLACE TABLE fact_rentals (
            rental_id BIGINT PRIMARY KEY,
            source_row_uid VARCHAR UNIQUE,
            registration_date DATE,
            start_date DATE,
            end_date DATE,
            version_en VARCHAR,
            is_renewal BOOLEAN,
            area_id INTEGER,
            project_id INTEGER,
            prop_type_en VARCHAR,
            prop_sub_type_en VARCHAR,
            canonical_property_type VARCHAR,
            rooms DOUBLE,
            canonical_bedroom VARCHAR,
            contract_amount_aed DOUBLE,
            annual_amount_aed DOUBLE,
            area_sqm DOUBLE,
            rent_per_sqft_aed DOUBLE,
            is_freehold BOOLEAN,
            usage_en VARCHAR,
            parking DOUBLE,
            total_properties INTEGER,
            nearest_metro VARCHAR,
            nearest_mall VARCHAR,
            nearest_landmark VARCHAR,
            source_file VARCHAR,
            imported_at TIMESTAMP
        )
    """)
    con.register("_fact_rentals_stage", df)
    con.execute("""
        INSERT INTO fact_rentals
        SELECT rental_id, source_row_uid, CAST(registration_date AS DATE), CAST(start_date AS DATE),
               CAST(end_date AS DATE), version_en, is_renewal, area_id, project_id, prop_type_en,
               prop_sub_type_en, canonical_property_type, rooms, canonical_bedroom, contract_amount_aed,
               annual_amount_aed, area_sqm, rent_per_sqft_aed, is_freehold, usage_en, parking,
               total_properties, nearest_metro, nearest_mall, nearest_landmark, source_file, imported_at
        FROM _fact_rentals_stage
    """)
    con.unregister("_fact_rentals_stage")
    return len(out)


def build_warehouse(con: duckdb.DuckDBPyConnection, scraped_db_path: Path = SCRAPED_DB_DEFAULT) -> dict[str, int]:
    ensure_schema(con)
    attach_scraped_db(con, scraped_db_path)
    n_areas = build_dim_area(con)
    n_projects = build_dim_project(con)
    hierarchy_stats = build_dim_project_hierarchy(con)
    n_sales = build_fact_sales(con)
    n_rentals = build_fact_rentals(con)
    enrich_dim_master_project(con)
    return {
        "dim_area": n_areas, "dim_project": n_projects, **hierarchy_stats,
        "fact_sales": n_sales, "fact_rentals": n_rentals,
    }
