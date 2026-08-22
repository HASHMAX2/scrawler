from ingestion.normalize import (
    canonical_bedroom_from_rentals,
    canonical_bedroom_from_rooms_en,
    canonical_key,
    canonical_property_type,
    parse_dld_date,
)


def test_canonical_bedroom_from_rooms_en_studio():
    assert canonical_bedroom_from_rooms_en("Studio") == "Studio"


def test_canonical_bedroom_from_rooms_en_counts():
    assert canonical_bedroom_from_rooms_en("1 B/R") == "1BR"
    assert canonical_bedroom_from_rooms_en("2 B/R") == "2BR"
    assert canonical_bedroom_from_rooms_en("4 B/R") == "4BR"


def test_canonical_bedroom_from_rooms_en_five_plus_bucketed():
    assert canonical_bedroom_from_rooms_en("5 B/R") == "5BR+"
    assert canonical_bedroom_from_rooms_en("9 B/R") == "5BR+"


def test_canonical_bedroom_from_rooms_en_non_bedroom_labels():
    # These are labels DLD puts in the ROOMS_EN column that are not bedroom
    # counts at all (a shop or office has no "bedrooms").
    assert canonical_bedroom_from_rooms_en("Hotel") == "Other"
    assert canonical_bedroom_from_rooms_en("Office") == "Other"
    assert canonical_bedroom_from_rooms_en("Shop") == "Other"
    assert canonical_bedroom_from_rooms_en("PENTHOUSE") == "Other"


def test_canonical_bedroom_from_rooms_en_null_is_none_not_unknown():
    # None means "field absent"; distinct from a recognized-but-non-bedroom label.
    assert canonical_bedroom_from_rooms_en(None) is None
    assert canonical_bedroom_from_rooms_en("") is None


def test_canonical_bedroom_from_rentals_villa_rooms_populated():
    assert canonical_bedroom_from_rentals(3.0, "Villa", "Villa") == "3BR"
    assert canonical_bedroom_from_rentals(6.0, "Villa", "Villa") == "5BR+"


def test_canonical_bedroom_from_rentals_studio_tag():
    assert canonical_bedroom_from_rentals(None, "Studio", "Unit") == "Studio"


def test_canonical_bedroom_from_rentals_unit_with_no_rooms_is_unknown():
    # This is the dominant real-world case: 95.8% of rental rows have no
    # ROOMS value and are Units (flats), not Villas. Must not be silently
    # dropped from bedroom-cut aggregation — "Unknown" keeps it visible.
    assert canonical_bedroom_from_rentals(None, "Flat", "Unit") == "Unknown"


def test_canonical_property_type_apartment_variants():
    assert canonical_property_type("Flat") == "Apartment"
    assert canonical_property_type("Residential Flats") == "Apartment"
    assert canonical_property_type("Studio") == "Apartment"


def test_canonical_property_type_villa_variants():
    assert canonical_property_type("Villa") == "Villa"
    assert canonical_property_type("Residential / Villas") == "Villa"
    assert canonical_property_type("Complex Villas") == "Villa"


def test_canonical_property_type_falls_back_to_prop_type():
    # Sub-type missing/unrecognized -> fall back to the coarser PROP_TYPE_EN.
    assert canonical_property_type(None, "Villa") == "Villa"


def test_canonical_property_type_unrecognized_is_other_not_guessed():
    assert canonical_property_type("Something Never Seen Before", None) == "Other"


def test_canonical_property_type_case_and_whitespace_insensitive():
    assert canonical_property_type("  flat  ") == "Apartment"
    assert canonical_property_type("FLAT") == "Apartment"


def test_canonical_key_basic():
    assert canonical_key("Jumeirah Village Circle") == "jumeirah village circle"


def test_canonical_key_punctuation_and_whitespace():
    assert canonical_key("Jumeirah Village Circle (JVC)") == "jumeirah village circle jvc"
    assert canonical_key("  Marsa   Dubai  ") == "marsa dubai"


def test_canonical_key_does_not_strip_tower_or_phase_tokens():
    # Aggressive stripping here would risk merging a master development with
    # a specific numbered tower — entity resolution must not do that silently.
    assert canonical_key("Azizi Venice Tower 15") == "azizi venice tower 15"
    assert canonical_key("Azizi Venice") == "azizi venice"
    assert canonical_key("Azizi Venice Tower 15") != canonical_key("Azizi Venice")


def test_canonical_key_none_and_empty():
    assert canonical_key(None) == ""
    assert canonical_key("") == ""


def test_parse_dld_date_extracts_date_part():
    assert parse_dld_date("2026-07-01 16:00:21") == "2026-07-01"


def test_parse_dld_date_none_and_garbage():
    assert parse_dld_date(None) is None
    assert parse_dld_date("not a date") is None
