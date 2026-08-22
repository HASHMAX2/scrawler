"""Regression coverage for the area-rollup bug found while manually reviewing the
dashboard against a real crawl: Propsearch tags a development's `Area` field at the
district/sub-community level (e.g. "JVC District 11"), never at the top-level
community name ("Jumeirah Village Circle") — so a naive `WHERE area_id = ?` against
the top-level area showed 0 developments even with 32 correctly scraped and linked
to their districts. `rollup_area_ids` (and everything built on it) must include the
whole descendant sub-tree.
"""
from __future__ import annotations

from dashboard import queries as q
from scraper.models import AreaPage, DevelopmentPage
from scraper.storage import Store


def _area(url, name, parent=None):
    page = AreaPage(url=url, name=name)
    page.parent_area = parent
    return page


def _dev(url, name, area_raw, units=None):
    return DevelopmentPage(url=url, name=name, area_raw=area_raw, total_units=units,
                            raw_status="Complete")


def _seed_hierarchy(store: Store) -> dict[str, int]:
    """Jumeirah Village Circle -> JVC District 11 -> (developments tagged to the
    district, matching what Propsearch actually publishes)."""
    top_id = store.upsert_area(_area("https://propsearch.ae/dubai/jvc", "Jumeirah Village Circle", "Dubai"))
    district_id = store.upsert_area(
        _area("https://propsearch.ae/dubai/jvc-district-11", "JVC District 11", "Jumeirah Village Circle")
    )
    store.upsert_development(_dev("https://propsearch.ae/dubai/tower-a", "Tower A", "JVC District 11", units=100),
                              area_id=None)
    store.upsert_development(_dev("https://propsearch.ae/dubai/tower-b", "Tower B", "JVC District 11", units=200),
                              area_id=None)
    store.backfill_area_ids()
    return {"top": top_id, "district": district_id}


def test_backfill_area_ids_links_developments_scraped_before_their_area(tmp_path):
    store = Store(tmp_path / "test.db")
    ids = _seed_hierarchy(store)
    row = store.conn.execute("SELECT area_id FROM developments WHERE name='Tower A'").fetchone()
    assert row["area_id"] == ids["district"]
    store.close()


def test_rollup_area_ids_includes_descendant_district(tmp_path):
    store = Store(tmp_path / "test.db")
    ids = _seed_hierarchy(store)
    conn = store.conn
    rollup = q.rollup_area_ids(conn, ids["top"])
    assert set(rollup) == {ids["top"], ids["district"]}
    store.close()


def test_area_unit_coverage_rolls_up_from_top_level_area(tmp_path):
    store = Store(tmp_path / "test.db")
    ids = _seed_hierarchy(store)
    conn = store.conn
    coverage = q.area_unit_coverage(conn, ids["top"])
    assert coverage["total"] == 2
    assert coverage["known_units"] == 2
    assert coverage["residential_units"] == 300
    store.close()


def test_list_areas_development_count_is_rolled_up(tmp_path):
    store = Store(tmp_path / "test.db")
    ids = _seed_hierarchy(store)
    conn = store.conn
    areas = {a["id"]: a for a in q.list_areas(conn)}
    assert areas[ids["top"]]["development_count"] == 2
    assert areas[ids["district"]]["development_count"] == 2
    store.close()


def test_list_developments_filtered_by_top_level_area_includes_district_devs(tmp_path):
    store = Store(tmp_path / "test.db")
    ids = _seed_hierarchy(store)
    conn = store.conn
    devs = q.list_developments(conn, area_id=ids["top"])
    assert {d["name"] for d in devs} == {"Tower A", "Tower B"}
    store.close()
