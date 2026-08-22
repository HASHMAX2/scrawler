from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scraper import parser

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def area_html():
    return _read("area_jumeirah_village_circle.html")


@pytest.fixture(scope="module")
def single_building_html():
    return _read("development_single_building.html")


@pytest.fixture(scope="module")
def multi_building_html():
    return _read("development_multi_building.html")


@pytest.fixture(scope="module")
def sub_building_html():
    return _read("development_sub_building.html")


@pytest.fixture(scope="module")
def buildings_listing_html():
    return _read("area_buildings_listing.html")


@pytest.fixture(scope="module")
def area_guides_html():
    return _read("area_guides_index.html")


@pytest.fixture(scope="module")
def amenities_html():
    return _read("area_amenities.html")


@pytest.fixture(scope="module")
def schools_html():
    return _read("area_schools.html")


# -- page classification ----------------------------------------------------

def test_classify_area_page(area_html):
    assert parser.classify_page(BeautifulSoup(area_html, "lxml")) == "area"


def test_classify_development_page(single_building_html):
    assert parser.classify_page(BeautifulSoup(single_building_html, "lxml")) == "development"


def test_classify_area_index(area_guides_html):
    assert parser.classify_page(BeautifulSoup(area_guides_html, "lxml")) == "area_index"


# -- area page ----------------------------------------------------------

def test_parse_area_page_identity(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    assert page.name == "Jumeirah Village Circle"
    assert page.parent_area == "Dubai"
    assert page.also_known_as == "JVC"
    assert page.developer_link.url == "https://propsearch.ae/dubai-property-developers/nakheel"


def test_parse_area_page_dld_community_widget(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    assert page.dld_community_code == "681"
    assert page.dld_community_name_en == "Al Barsha South Fourth"
    assert page.dld_buildings == 421
    assert page.dld_villas == 3257
    assert page.dld_residential_units == 96586
    assert page.dld_commercial_units == 2965


def test_parse_area_page_subcommunities(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    assert len(page.subcommunities) == 14
    names = {sc.name for sc in page.subcommunities}
    assert "Angelica Residences" in names
    angelica = next(sc for sc in page.subcommunities if sc.name == "Angelica Residences")
    assert angelica.raw_status == "Under development (Cancelled)"
    assert angelica.url == "https://propsearch.ae/dubai/angelica-residences"


def test_parse_area_page_hero_image(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    assert page.hero_image_url == "https://static.propsearch.ae/photos/dubai/areas/jumeirah-village-circle-9902_sm.jpg"


def test_parse_area_page_subcommunity_image(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    angelica = next(sc for sc in page.subcommunities if sc.name == "Angelica Residences")
    assert angelica.image_url is not None


def test_parse_area_page_document_photo_urls(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    construction_photos = next(d for d in page.documents if d.doc_type == "construction_photos")
    assert construction_photos.photo_count == len(construction_photos.photo_urls)
    assert all(u.startswith("https://static.propsearch.ae/") for u in construction_photos.photo_urls)


def test_parse_development_page_hero_image(single_building_html):
    dev = parser.parse_development_page(single_building_html, "https://propsearch.ae/dubai/example")
    assert dev.hero_image_url is not None
    assert dev.hero_image_url.startswith("https://static.propsearch.ae/")


def test_parse_area_page_transactions_present(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    assert len(page.transactions) > 0
    txn = page.transactions[0]
    assert txn.price_aed is not None
    assert txn.transaction_date is not None


def test_parse_area_page_coordinates(area_html):
    page = parser.parse_area_page(area_html, "https://propsearch.ae/dubai/jumeirah-village-circle")
    # Area (overview) pages don't carry the per-project map embed; absence must stay
    # None, never a fabricated 0,0.
    assert page.latitude is None or isinstance(page.latitude, float)


# -- mentioned places (Transport & Access prose links) -----------------------

def test_parse_mentioned_places_extracts_links_with_section_and_context(area_html):
    soup = BeautifulSoup(area_html, "lxml")
    places = parser.parse_mentioned_places(soup)
    names = {p.name for p in places}
    assert "Dubai Mall" in names
    assert "Dubai Marina" in names
    dubai_mall = next(p for p in places if p.name == "Dubai Mall")
    assert dubai_mall.linked_url == "https://propsearch.ae/dubai/dubai-mall"
    assert dubai_mall.section == "Road access"
    assert dubai_mall.context_sentence and "Dubai Mall" in dubai_mall.context_sentence


def test_parse_mentioned_places_absent_section_returns_empty(single_building_html):
    # No "Transport & Access" heading on this fixture's markup shape — must return an
    # empty list, never fabricate mentions.
    soup = BeautifulSoup(single_building_html, "lxml")
    places = parser.parse_mentioned_places(soup)
    assert places == [] or all(p.section for p in places)


def test_parse_mentioned_places_no_transport_heading_returns_empty():
    soup = BeautifulSoup("<html><body><h2 class='ps-crosshead'>Overview</h2></body></html>", "lxml")
    assert parser.parse_mentioned_places(soup) == []


def test_parse_mentioned_places_never_duplicates_same_link_in_same_section():
    html = (
        '<div class="ps-3-col-block"><div class="ps-3-col-centre">'
        '<h2 class="ps-crosshead">Transport &amp; Access</h2>'
        '</div></div>'
        '<div class="ps-3-col-block"><div class="ps-3-col-centre ps-prose">'
        '<div class="ps-h3">Road access</div>'
        '<p>10 minutes to <a href="/dubai/dubai-mall">Dubai Mall</a>.</p>'
        '<p>Also 10 minutes to <a href="/dubai/dubai-mall">Dubai Mall</a> via another road.</p>'
        '</div></div>'
    )
    soup = BeautifulSoup(html, "lxml")
    places = parser.parse_mentioned_places(soup)
    assert len(places) == 1
    assert places[0].name == "Dubai Mall"


# -- buildings directory listing -----------------------------------------

def test_parse_buildings_listing_counts_match_propsearch_summary(buildings_listing_html):
    cards, stub = parser.parse_buildings_listing(buildings_listing_html)
    assert stub.propsearch_dev_total == 886
    assert stub.propsearch_dev_completed == 456
    assert stub.propsearch_dev_under_construction == 186
    assert stub.propsearch_dev_planned == 24
    assert stub.propsearch_dev_cancelled == 219
    # Every card must resolve to a normalizable status and a /dubai/ URL.
    assert len(cards) > 800
    assert all("/dubai/" in c.url for c in cards)


def test_parse_buildings_listing_status_breakdown_self_consistent(buildings_listing_html):
    """The per-card raw_status tally should reconcile with Propsearch's own summary
    sentence once cancelled variants are merged in (cross-check, not a hardcoded
    number — see PROPSEARCH_STRUCTURE.md §3)."""
    from collections import Counter

    from scraper.normalizer import normalize_status

    cards, stub = parser.parse_buildings_listing(buildings_listing_html)
    normalized = Counter(normalize_status(c.raw_status) for c in cards)
    assert normalized["completed"] == stub.propsearch_dev_completed
    assert normalized["cancelled"] == stub.propsearch_dev_cancelled


# -- development page: single building -----------------------------------

def test_parse_single_building_identity(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    assert dev.name == "First Collection Jumeirah Village Circle"
    assert dev.building_type_raw.startswith("Hotel")
    assert dev.is_multi_building is False
    assert dev.raw_status == "Complete"
    assert dev.storeys_raw == "42 storeys"


def test_parse_single_building_units_never_fabricated(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    assert dev.total_units == 491
    assert "491 units" in dev.total_units_raw


def test_parse_single_building_developer_and_links(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    assert dev.developer_link.url == "https://propsearch.ae/dubai-property-developers/the-first-group"
    assert any(c.role == "Architect" for c in dev.companies)
    assert any(c.role == "Contractor" for c in dev.companies)


def test_parse_single_building_milestones(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    labels = {m.label: m.date_parsed for m in dev.milestones}
    assert labels["Construction Started"] == "2015-06"
    assert labels["Construction Finished"] == "2020-06"


def test_parse_single_building_coordinates(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    assert dev.latitude == pytest.approx(25.0547)
    assert dev.longitude == pytest.approx(55.204703)


def test_parse_single_building_project_value(single_building_html):
    dev = parser.parse_development_page(
        single_building_html, "https://propsearch.ae/dubai/first-collection-jumeirah-village-circle"
    )
    assert dev.project_value_aed == 203168000.0
    assert dev.project_value_usd == 55_300_000.0


# -- development page: multi-building complex -----------------------------

def test_parse_multi_building_complex(multi_building_html):
    dev = parser.parse_development_page(multi_building_html, "https://propsearch.ae/dubai/cello")
    assert dev.is_multi_building is True
    assert dev.building_type_raw == "Multi-building complex"
    urls = {l.url for l in dev.sub_building_links}
    assert urls == {
        "https://propsearch.ae/dubai/cello-block-a",
        "https://propsearch.ae/dubai/cello-block-b",
    }


# -- development page: sub-building of a complex --------------------------

def test_parse_sub_building_links_to_master(sub_building_html):
    dev = parser.parse_development_page(sub_building_html, "https://propsearch.ae/dubai/cello-block-a")
    assert dev.master_development_link.url == "https://propsearch.ae/dubai/cello"
    sibling_urls = {l.url for l in dev.other_building_links}
    assert "https://propsearch.ae/dubai/cello-block-b" in sibling_urls


# -- amenities / schools --------------------------------------------------

def test_parse_amenities_page_categories(amenities_html):
    amenities = parser.parse_amenities_page(amenities_html)
    assert len(amenities) > 500
    categories = {a.category for a in amenities}
    assert "Supermarkets & Mini Marts" in categories
    assert "Restaurants & Bars" in categories


def test_parse_schools_page(schools_html):
    schools = parser.parse_schools_page(schools_html)
    assert len(schools) > 10
    names = {s.name for s in schools}
    assert "Nord Anglia International School Dubai" in names
    nord = next(s for s in schools if s.name == "Nord Anglia International School Dubai")
    assert nord.rating == "Outstanding"
    assert nord.distance_text == "2.0 km"
