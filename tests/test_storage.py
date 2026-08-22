import pytest

from scraper.models import (
    AreaPage, BuildingLinkRef, DevelopmentPage, DocumentRef, LinkRef, MilestoneRecord, SubCommunityRef,
)
from scraper.storage import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def _dev(url="https://propsearch.ae/dubai/example-tower", name="Example Tower",
         raw_status="Complete", total_units=100):
    return DevelopmentPage(
        url=url, name=name, building_type_raw="Residential building",
        raw_status=raw_status, total_units=total_units,
        total_units_raw=f"The development contains a total of {total_units} units.",
        developer_link=LinkRef(url="https://propsearch.ae/dubai-property-developers/acme", text="Acme"),
    )


def _area(url="https://propsearch.ae/dubai/example-area", name="Example Area"):
    return AreaPage(url=url, name=name)


# -- deduplication (brief §15) --------------------------------------------

def test_rerunning_upsert_development_does_not_duplicate(store):
    dev1_id = store.upsert_development(_dev(), area_id=None)
    dev2_id = store.upsert_development(_dev(), area_id=None)
    assert dev1_id == dev2_id
    count = store.conn.execute("SELECT COUNT(*) c FROM developments").fetchone()["c"]
    assert count == 1


def test_rerunning_upsert_area_does_not_duplicate(store):
    a1 = store.upsert_area(_area())
    a2 = store.upsert_area(_area())
    assert a1 == a2
    count = store.conn.execute("SELECT COUNT(*) c FROM areas").fetchone()["c"]
    assert count == 1


def test_dedup_keyed_on_url_not_name(store):
    """Two different developments that happen to share a display name must remain
    distinct records — the brief requires URL/ID-based dedup, not name matching."""
    id1 = store.upsert_development(_dev(url="https://propsearch.ae/dubai/tower-1", name="Marina Tower"),
                                    area_id=None)
    id2 = store.upsert_development(_dev(url="https://propsearch.ae/dubai/tower-2", name="Marina Tower"),
                                    area_id=None)
    assert id1 != id2
    count = store.conn.execute("SELECT COUNT(*) c FROM developments").fetchone()["c"]
    assert count == 2


# -- incremental updates / change detection (brief §16) --------------------

def test_new_development_logged_as_new_record(store):
    dev_id = store.upsert_development(_dev(), area_id=None, job_id=None)
    rows = store.conn.execute(
        "SELECT * FROM change_log WHERE entity_type='development' AND entity_id=?", (dev_id,)
    ).fetchall()
    assert any(r["change_kind"] == "new_record" for r in rows)


def test_status_change_is_logged(store):
    dev_id = store.upsert_development(_dev(raw_status="Under development"), area_id=None)
    store.upsert_development(_dev(raw_status="Complete"), area_id=None)
    rows = store.conn.execute(
        "SELECT * FROM change_log WHERE entity_type='development' AND entity_id=? AND field_name='raw_status'",
        (dev_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["old_value"] == "Under development"
    assert rows[0]["new_value"] == "Complete"


def test_unit_count_change_is_logged(store):
    dev_id = store.upsert_development(_dev(total_units=100), area_id=None)
    store.upsert_development(_dev(total_units=250), area_id=None)
    rows = store.conn.execute(
        "SELECT * FROM change_log WHERE entity_type='development' AND entity_id=? AND field_name='total_units'",
        (dev_id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["old_value"] == "100"
    assert rows[0]["new_value"] == "250"


def test_no_change_logged_when_nothing_changed(store):
    dev_id = store.upsert_development(_dev(), area_id=None)
    store.upsert_development(_dev(), area_id=None)
    rows = store.conn.execute(
        "SELECT * FROM change_log WHERE entity_type='development' AND entity_id=? AND change_kind='field_changed'",
        (dev_id,),
    ).fetchall()
    assert rows == []


def test_missing_unit_count_does_not_overwrite_known_value(store):
    """A partial re-scrape that fails to find the Units field must not blank out a
    previously-captured value (brief §6: never treat missing data as a real value)."""
    dev_id = store.upsert_development(_dev(total_units=491), area_id=None)
    incomplete = _dev(total_units=None)
    incomplete.total_units_raw = None
    store.upsert_development(incomplete, area_id=None)
    row = store.conn.execute("SELECT total_units FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["total_units"] == 491


def test_development_marked_inactive_when_absent_from_listing(store):
    area_id = store.upsert_area(_area())
    dev_id = store.upsert_development(_dev(), area_id=area_id)
    store.mark_missing_developments(seen_urls=set(), area_id=area_id, job_id=None)
    row = store.conn.execute("SELECT is_active FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["is_active"] == 0
    disappeared = store.conn.execute(
        "SELECT * FROM change_log WHERE entity_id=? AND change_kind='disappeared'", (dev_id,)
    ).fetchall()
    assert len(disappeared) == 1


def test_development_stays_active_when_present_in_listing(store):
    area_id = store.upsert_area(_area())
    dev = _dev()
    dev_id = store.upsert_development(dev, area_id=area_id)
    store.mark_missing_developments(seen_urls={dev.url}, area_id=area_id, job_id=None)
    row = store.conn.execute("SELECT is_active FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["is_active"] == 1


# -- sub-building relationship (brief §7) ----------------------------------

def test_sub_building_linked_to_master_development(store):
    master = _dev(url="https://propsearch.ae/dubai/cello", name="Cello")
    master_id = store.upsert_development(master, area_id=None)

    sub = _dev(url="https://propsearch.ae/dubai/cello-block-a", name="Cello Block A")
    sub.master_development_link = LinkRef(url="https://propsearch.ae/dubai/cello", text="Cello")
    store.upsert_development(sub, area_id=None)

    row = store.conn.execute(
        "SELECT master_development_id FROM developments WHERE url=?",
        ("https://propsearch.ae/dubai/cello-block-a",),
    ).fetchone()
    assert row["master_development_id"] == master_id


def test_multi_building_complex_creates_buildings_rows(store):
    master = _dev(url="https://propsearch.ae/dubai/cello", name="Cello")
    master.is_multi_building = True
    master.sub_building_links = [
        LinkRef(url="https://propsearch.ae/dubai/cello-block-a", text="Cello Block A"),
        LinkRef(url="https://propsearch.ae/dubai/cello-block-b", text="Cello Block B"),
    ]
    master_id = store.upsert_development(master, area_id=None)
    rows = store.conn.execute("SELECT * FROM buildings WHERE development_id=?", (master_id,)).fetchall()
    assert len(rows) == 2
    assert {r["name"] for r in rows} == {"Cello Block A", "Cello Block B"}


# -- developer dedup --------------------------------------------------------

def test_developer_deduplicated_by_url(store):
    id1 = store.upsert_development(
        _dev(url="https://propsearch.ae/dubai/tower-1"), area_id=None
    )
    id2 = store.upsert_development(
        _dev(url="https://propsearch.ae/dubai/tower-2"), area_id=None
    )
    row1 = store.conn.execute("SELECT developer_id FROM developments WHERE id=?", (id1,)).fetchone()
    row2 = store.conn.execute("SELECT developer_id FROM developments WHERE id=?", (id2,)).fetchone()
    assert row1["developer_id"] == row2["developer_id"]
    count = store.conn.execute("SELECT COUNT(*) c FROM developers").fetchone()["c"]
    assert count == 1


# -- daily request budget ----------------------------------------------------

def test_record_request_increments_and_persists(store):
    assert store.requests_used_today() == 0
    assert store.record_request() == 1
    assert store.record_request() == 2
    assert store.requests_used_today() == 2


# -- discover/enrich stub developments ---------------------------------------

def test_upsert_development_stub_creates_stub_row(store):
    card = BuildingLinkRef(name="Tower A", url="https://propsearch.ae/dubai/tower-a", raw_status="Complete")
    dev_id = store.upsert_development_stub(card, area_id=None)
    row = store.conn.execute("SELECT * FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["is_stub"] == 1
    assert row["enriched_at"] is None
    assert row["name"] == "Tower A"
    assert row["normalized_status"] == "completed"


def test_full_upsert_clears_stub_flag(store):
    # A discovery-mode stub, later fully enriched, must flip is_stub off — a full
    # parse must never leave a row silently marked as still-unenriched.
    card = BuildingLinkRef(name="Tower A", url="https://propsearch.ae/dubai/tower-a", raw_status=None)
    dev_id = store.upsert_development_stub(card, area_id=None)
    assert store.conn.execute("SELECT is_stub FROM developments WHERE id=?", (dev_id,)).fetchone()["is_stub"] == 1

    full_dev_id = store.upsert_development(_dev(url="https://propsearch.ae/dubai/tower-a"), area_id=None)
    assert full_dev_id == dev_id  # same row, matched by URL
    row = store.conn.execute("SELECT is_stub, enriched_at FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["is_stub"] == 0
    assert row["enriched_at"] is not None


def test_upsert_development_stub_never_downgrades_an_enriched_row(store):
    full_id = store.upsert_development(_dev(url="https://propsearch.ae/dubai/tower-a"), area_id=None)
    card = BuildingLinkRef(name="Tower A", url="https://propsearch.ae/dubai/tower-a", raw_status="Complete")
    same_id = store.upsert_development_stub(card, area_id=None)
    assert same_id == full_id
    row = store.conn.execute("SELECT is_stub FROM developments WHERE id=?", (full_id,)).fetchone()
    assert row["is_stub"] == 0  # still enriched, not reset to stub


def test_stub_development_urls_only_returns_stubs(store):
    stub_id = store.upsert_development_stub(
        BuildingLinkRef(name="Stub Tower", url="https://propsearch.ae/dubai/stub-tower", raw_status=None), area_id=None
    )
    store.upsert_development(_dev(url="https://propsearch.ae/dubai/full-tower"), area_id=None)
    urls = {r["url"] for r in store.stub_development_urls()}
    assert urls == {"https://propsearch.ae/dubai/stub-tower"}


def test_update_candidates_prioritizes_under_construction(store):
    store.upsert_development(_dev(url="https://propsearch.ae/dubai/done-tower", raw_status="Complete"), area_id=None)
    store.upsert_development(_dev(url="https://propsearch.ae/dubai/wip-tower", raw_status="Under construction"), area_id=None)
    candidates = store.update_candidates()
    urls_in_order = [r["url"] for r in candidates]
    assert urls_in_order.index("https://propsearch.ae/dubai/wip-tower") < urls_in_order.index("https://propsearch.ae/dubai/done-tower")


def test_update_candidates_excludes_stubs(store):
    store.upsert_development_stub(
        BuildingLinkRef(name="Stub Tower", url="https://propsearch.ae/dubai/stub-tower", raw_status=None), area_id=None
    )
    store.upsert_development(_dev(url="https://propsearch.ae/dubai/full-tower"), area_id=None)
    urls = {r["url"] for r in store.update_candidates()}
    assert urls == {"https://propsearch.ae/dubai/full-tower"}


# -- mentioned_places backfill (from already-cached raw HTML) ----------------

_TRANSPORT_HTML = (
    '<div class="ps-3-col-block"><div class="ps-3-col-centre">'
    '<h2 class="ps-crosshead">Transport &amp; Access</h2>'
    '</div></div>'
    '<div class="ps-3-col-block"><div class="ps-3-col-centre ps-prose">'
    '<div class="ps-h3">Road access</div>'
    '<p>10 minutes to <a href="/dubai/dubai-mall">Dubai Mall</a>.</p>'
    '</div></div>'
)


def test_backfill_mentioned_places_extracts_from_cached_raw_html(store, tmp_path):
    area_id = store.upsert_area(_area())
    area_row = store.conn.execute("SELECT url FROM areas WHERE id=?", (area_id,)).fetchone()
    store.log_scraped_page(area_row["url"], area_row["url"], 200, _TRANSPORT_HTML, tmp_path / "raw", "area")

    added = store.backfill_mentioned_places()
    assert added == 1
    row = store.conn.execute("SELECT name, linked_url, section, source_area_id FROM mentioned_places").fetchone()
    assert row["name"] == "Dubai Mall"
    assert row["section"] == "Road access"
    assert row["source_area_id"] == area_id


def test_backfill_mentioned_places_is_idempotent(store, tmp_path):
    area_id = store.upsert_area(_area())
    area_row = store.conn.execute("SELECT url FROM areas WHERE id=?", (area_id,)).fetchone()
    store.log_scraped_page(area_row["url"], area_row["url"], 200, _TRANSPORT_HTML, tmp_path / "raw", "area")

    assert store.backfill_mentioned_places() == 1
    assert store.backfill_mentioned_places() == 0
    count = store.conn.execute("SELECT COUNT(*) c FROM mentioned_places").fetchone()["c"]
    assert count == 1


# -- image URLs (hero images, sub-community thumbnails, document galleries) --

def test_upsert_area_persists_hero_image_url(store):
    area = _area()
    area.hero_image_url = "https://static.propsearch.ae/dubai-locations/example-area_xl.jpg"
    area_id = store.upsert_area(area)
    row = store.conn.execute("SELECT hero_image_url FROM areas WHERE id=?", (area_id,)).fetchone()
    assert row["hero_image_url"] == area.hero_image_url


def test_upsert_area_hero_image_not_blanked_by_partial_rescrape(store):
    area = _area()
    area.hero_image_url = "https://static.propsearch.ae/dubai-locations/example-area_xl.jpg"
    area_id = store.upsert_area(area)

    partial = _area()  # no hero_image_url set on this re-scrape
    store.upsert_area(partial)
    row = store.conn.execute("SELECT hero_image_url FROM areas WHERE id=?", (area_id,)).fetchone()
    assert row["hero_image_url"] == area.hero_image_url


def test_upsert_area_persists_subcommunity_image_url(store):
    area = _area()
    area.subcommunities = [SubCommunityRef(
        name="Example Sub", url="https://propsearch.ae/dubai/example-sub",
        image_url="https://static.propsearch.ae/dubai-locations/example-sub.jpg",
    )]
    store.upsert_area(area)
    row = store.conn.execute("SELECT image_url FROM sub_communities WHERE name='Example Sub'").fetchone()
    assert row["image_url"] == "https://static.propsearch.ae/dubai-locations/example-sub.jpg"


def test_upsert_development_persists_hero_image_url(store):
    dev = _dev()
    dev.hero_image_url = "https://static.propsearch.ae/dubai-locations/example-tower_xl.jpg"
    dev_id = store.upsert_development(dev, area_id=None)
    row = store.conn.execute("SELECT hero_image_url FROM developments WHERE id=?", (dev_id,)).fetchone()
    assert row["hero_image_url"] == dev.hero_image_url


def test_upsert_development_persists_document_photo_urls(store):
    dev = _dev()
    dev.documents = [DocumentRef(
        doc_type="construction_photos", label="Construction Photos", photo_count=2,
        photo_urls=["https://static.propsearch.ae/a.jpg", "https://static.propsearch.ae/b.jpg"],
    )]
    dev_id = store.upsert_development(dev, area_id=None)
    row = store.conn.execute(
        "SELECT photo_urls_json FROM documents WHERE development_id=? AND doc_type='construction_photos'",
        (dev_id,),
    ).fetchone()
    import json
    assert json.loads(row["photo_urls_json"]) == dev.documents[0].photo_urls


# -- migrate=False (read-only callers must not contend for the write lock) ---

def test_migrate_false_still_creates_schema_and_columns(tmp_path):
    # A read-only Store() must still be usable — schema + column migrations run
    # regardless of the flag; only the (write-heavy) data backfills are skipped.
    store = Store(tmp_path / "test.db", migrate=False)
    row = store.conn.execute("PRAGMA table_info(areas)").fetchall()
    columns = {r["name"] for r in row}
    assert "hero_image_url" in columns
    assert "area_type" in columns
    store.close()


def test_migrate_false_skips_data_backfills(store, tmp_path):
    # Seed data that a backfill would normally act on, then confirm a migrate=False
    # Store() doesn't touch it.
    area = _area()
    area.also_known_as = "Example Alias"
    store.upsert_area(area)
    store.close()

    readonly = Store(tmp_path / "test.db", migrate=False)
    count = readonly.conn.execute("SELECT COUNT(*) c FROM entity_aliases").fetchone()["c"]
    assert count == 0  # backfill_aliases() never ran
    readonly.close()
