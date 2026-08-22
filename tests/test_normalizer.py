from scraper.normalizer import (
    classify_area_type, normalize_alias, normalize_status, parse_coordinates, parse_fuzzy_date,
    parse_int, parse_money, parse_project_value, parse_size_sqft, parse_total_units,
    parse_transaction_date, split_aliases,
)


def test_normalize_status_basic_vocabulary():
    assert normalize_status("Complete") == "completed"
    assert normalize_status("Under development") == "under_construction"
    assert normalize_status("Planned") == "planned"


def test_normalize_status_cancelled_overrides_under_development():
    # "Under development (Cancelled)" must map to cancelled, not under_construction —
    # cancelled/on-hold/delayed patterns must be checked before the general pattern.
    assert normalize_status("Under development (Cancelled)") == "cancelled"
    assert normalize_status("Planned (Cancelled)") == "cancelled"


def test_normalize_status_on_hold_overrides_under_development():
    assert normalize_status("Under development (On hold)") == "on_hold"


def test_normalize_status_unknown_maps_to_other():
    assert normalize_status(None) == "other"
    assert normalize_status("") == "other"
    assert normalize_status("Something Propsearch has never shown before") == "other"


def test_parse_int_handles_commas_and_missing():
    assert parse_int("3,257") == 3257
    assert parse_int("421") == 421
    assert parse_int(None) is None
    assert parse_int("") is None
    assert parse_int("no digits here") is None


def test_parse_total_units_extracts_from_sentence():
    value, raw = parse_total_units("The development contains a total of 491 units.")
    assert value == 491
    assert raw == "The development contains a total of 491 units."


def test_parse_total_units_missing_stays_none_not_zero():
    # Brief §6: never treat missing unit data as zero.
    value, raw = parse_total_units("No unit information published for this project.")
    assert value is None
    assert raw == "No unit information published for this project."
    value2, raw2 = parse_total_units(None)
    assert value2 is None and raw2 is None


def test_parse_fuzzy_date_month_year():
    assert parse_fuzzy_date("Construction began in June 2015.") == "2015-06"


def test_parse_fuzzy_date_quarter():
    assert parse_fuzzy_date("construction set to begin in Q1 2025") == "2025-Q1"


def test_parse_fuzzy_date_bare_year():
    assert parse_fuzzy_date("The estimated opening date was 2021.") == "2021"


def test_parse_fuzzy_date_none_when_absent():
    assert parse_fuzzy_date("No dates mentioned here.") is None
    assert parse_fuzzy_date(None) is None


def test_parse_project_value():
    aed, usd = parse_project_value("AED 203,168,000 (USD 55.3m)")
    assert aed == 203168000.0
    assert usd == 55_300_000.0


def test_parse_transaction_date():
    assert parse_transaction_date("31st Jul 2026") == "2026-07-31"
    assert parse_transaction_date("31 Jul 2026") == "2026-07-31"


def test_parse_money():
    assert parse_money("AED 1,100,000") == 1100000.0


def test_parse_size_sqft():
    assert parse_size_sqft("951 sq. ft") == 951.0


def test_parse_coordinates_from_maps_embed_iframe():
    html = (
        '<iframe src=" https://www.google.com/maps/embed/v1/place?key=XYZ123'
        '&q=25.0547,55.204703"></iframe>'
    )
    lat, lng = parse_coordinates(html)
    assert lat == 25.0547
    assert lng == 55.204703


def test_parse_coordinates_missing():
    assert parse_coordinates("<html>no map here</html>") == (None, None)


# -- classify_area_type -------------------------------------------------------
# Every name below is a REAL row from the scraped database (see PROPSEARCH_STRUCTURE.md
# investigation) — this isn't a guessed heuristic, it's verified against actual data.

def test_classify_area_type_detects_all_known_malls():
    for name in ["Dubai Mall", "Circle Mall", "Mall of the Emirates", "First Avenue Mall",
                 "Barsha Mall", "Dubai Hills Mall"]:
        assert classify_area_type(name) == "mall"


def test_classify_area_type_detects_curated_landmarks():
    assert classify_area_type("Ski Dubai") == "landmark"
    assert classify_area_type("Skydive Dubai") == "landmark"
    assert classify_area_type("The Walk JBR") == "landmark"


def test_classify_area_type_does_not_misclassify_real_communities_with_null_dld_code():
    # These are real, well-known residential communities that happen to lack a
    # matched DLD community code in this dataset — dld_community_code IS NULL alone
    # was rejected as a classifier precisely because of cases like these.
    for name in ["The Springs", "The Greens", "The Meadows", "Arjan", "Bur Dubai",
                  "Victory Heights", "Circle Villas"]:
        assert classify_area_type(name) == "community"


def test_classify_area_type_mall_keyword_is_whole_word():
    # Must not false-positive on a name that merely contains "mall" as a substring
    # of a longer word.
    assert classify_area_type("Emallville") == "community"


def test_classify_area_type_case_insensitive():
    assert classify_area_type("DUBAI MALL") == "mall"
    assert classify_area_type("dubai mall") == "mall"


def test_classify_area_type_none_and_empty():
    assert classify_area_type(None) == "community"
    assert classify_area_type("") == "community"


# -- alias splitting/normalization ---------------------------------------------

def test_split_aliases_single_value():
    # Real observed data today — a single abbreviation, no separators.
    assert split_aliases("JVC") == ["JVC"]


def test_split_aliases_comma_separated():
    assert split_aliases("JVC, Jumeirah Village Circle Dubai") == ["JVC", "Jumeirah Village Circle Dubai"]


def test_split_aliases_and_separated():
    assert split_aliases("JVC and Jumeirah Village") == ["JVC", "Jumeirah Village"]


def test_split_aliases_slash_and_semicolon():
    assert split_aliases("JVC/JVT; Jumeirah Village") == ["JVC", "JVT", "Jumeirah Village"]


def test_split_aliases_none_and_empty():
    assert split_aliases(None) == []
    assert split_aliases("") == []
    assert split_aliases("   ") == []


def test_normalize_alias_casefolds_and_collapses_whitespace():
    assert normalize_alias("  JVC  ") == "jvc"
    assert normalize_alias("Jumeirah   Village   Circle") == "jumeirah village circle"
