from scraper.url_utils import (
    area_subpage_kind, canonicalize, is_allowed, is_area_guides_index,
    slug_from_dubai_url,
)


def test_canonicalize_strips_fragment_and_trailing_slash():
    assert canonicalize("https://propsearch.ae/dubai/jvc/#section") == \
        "https://propsearch.ae/dubai/jvc"


def test_canonicalize_resolves_relative_url():
    assert canonicalize("/dubai/cello", base="https://propsearch.ae/dubai/jvc") == \
        "https://propsearch.ae/dubai/cello"


def test_canonicalize_keeps_page_param_drops_others():
    result = canonicalize("https://propsearch.ae/dubai/area-guides?page=2&utm_source=x")
    assert result == "https://propsearch.ae/dubai/area-guides?page=2"


def test_canonicalize_lowercases_host():
    assert canonicalize("https://PropSearch.AE/dubai/jvc") == "https://propsearch.ae/dubai/jvc"


def test_is_allowed_accepts_dubai_slug():
    assert is_allowed("https://propsearch.ae/dubai/jumeirah-village-circle")


def test_is_allowed_rejects_bare_dubai():
    assert not is_allowed("https://propsearch.ae/dubai")
    assert not is_allowed("https://propsearch.ae/dubai/")


def test_is_allowed_rejects_live_listing_search():
    assert not is_allowed("https://propsearch.ae/dubai-properties-for-sale/by-location/jvc")


def test_is_allowed_rejects_developer_and_contractor_pages():
    # Deliberately excluded from the crawl frontier to avoid an area-scoped crawl
    # ballooning into every project a developer has across all of Dubai.
    assert not is_allowed("https://propsearch.ae/dubai-property-developers/nakheel")
    assert not is_allowed("https://propsearch.ae/dubai-construction-companies/norr-group")


def test_is_allowed_rejects_other_hosts():
    assert not is_allowed("https://bayut.com/dubai/jvc")


def test_is_allowed_rejects_assets():
    assert not is_allowed("https://propsearch.ae/dubai/jvc.jpg")
    assert not is_allowed("https://static.propsearch.ae/photos/dubai/areas/jvc.jpg")


def test_is_allowed_rejects_account_and_pro_tools():
    assert not is_allowed("https://propsearch.ae/account/profile")
    assert not is_allowed("https://propsearch.ae/pro-tools/transaction-search")
    assert not is_allowed("https://propsearch.ae/dubai/jvc/properties-buy-rent")


def test_slug_from_dubai_url():
    assert slug_from_dubai_url("https://propsearch.ae/dubai/jumeirah-village-circle") == \
        "jumeirah-village-circle"
    assert slug_from_dubai_url("https://propsearch.ae/dubai/cello/buildings") == "cello"


def test_slug_from_dubai_url_excludes_area_guides():
    assert slug_from_dubai_url("https://propsearch.ae/dubai/area-guides") is None


def test_area_subpage_kind():
    assert area_subpage_kind("https://propsearch.ae/dubai/jvc/buildings") == "buildings"
    assert area_subpage_kind("https://propsearch.ae/dubai/jvc/amenities") == "amenities"
    assert area_subpage_kind("https://propsearch.ae/dubai/jvc") is None
    assert area_subpage_kind("https://propsearch.ae/dubai/jvc/cello") is None


def test_is_area_guides_index():
    assert is_area_guides_index("https://propsearch.ae/dubai/area-guides")
    assert is_area_guides_index("https://propsearch.ae/dubai/area-guides?page=2")
    assert not is_area_guides_index("https://propsearch.ae/dubai/jvc")
