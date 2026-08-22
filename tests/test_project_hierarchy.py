from ingestion.project_hierarchy import display_name_from_key, extract_building_suffix, slugify


def test_trailing_number_basic():
    r = extract_building_suffix("AZIZI VENICE 14")
    assert r.master_key == "azizi venice"
    assert r.building_label == "14"
    assert r.method == "trailing_number"


def test_trailing_number_case_and_whitespace_insensitive():
    # Real observed variants for the same tower.
    for raw in ["AZIZI VENICE 14", "azizi venice 14", "  Azizi   Venice  14  "]:
        r = extract_building_suffix(raw)
        assert r.master_key == "azizi venice"
        assert r.building_label == "14"


def test_trailing_number_with_filler_word_tower():
    r = extract_building_suffix("Azizi Venice Tower 15")
    assert r.master_key == "azizi venice"
    assert r.building_label == "15"
    assert r.method == "trailing_number"


def test_trailing_number_with_hyphen_before_number():
    # canonical_key turns "-" into a space, so this still hits the numeric
    # pattern rather than the hyphen-split fallback.
    r = extract_building_suffix("AZIZI VENICE - 15")
    assert r.master_key == "azizi venice"
    assert r.building_label == "15"


def test_different_tower_numbers_share_master_but_differ_in_building():
    a = extract_building_suffix("Azizi Venice 9")
    b = extract_building_suffix("Azizi Venice 12")
    assert a.master_key == b.master_key == "azizi venice"
    assert a.building_label != b.building_label


def test_hyphen_split_named_sub_building():
    # Real name observed in the actual DLD export.
    r = extract_building_suffix("Creek Beach - Canopy - Moor")
    assert r.master_key == "creek beach"
    assert r.building_label == "Canopy - Moor"
    assert r.method == "hyphen_split"


def test_hyphen_split_simple():
    r = extract_building_suffix("Remraam - Al Ramth")
    assert r.master_key == "remraam"
    assert r.building_label == "Al Ramth"


def test_parenthetical_enumeration_is_not_a_hyphen_split():
    # Real observed name. Must NOT extract "1" as a trailing tower number
    # (it's not at the end), and the hyphens inside "(Lavender - Gardenia -
    # Rose)" are an enumeration, not a master/building separator — splitting
    # on them would produce a nonsensical building label.
    r = extract_building_suffix("EMIRATES GARDEN 1 (LAVENDER - GARDENIA - ROSE)")
    assert r.building_label is None
    assert r.method == "none"


def test_no_trailing_number_no_hyphen_stays_whole():
    r = extract_building_suffix("CLAYDON HOUSE BY ELLINGTON")
    assert r.master_key == "claydon house by ellington"
    assert r.building_label is None
    assert r.method == "none"


def test_unrelated_project_sharing_a_word_does_not_merge():
    # "Venice" alone (hypothetical unrelated project) must NOT collapse to
    # the same master_key as "Azizi Venice N" towers.
    unrelated = extract_building_suffix("Venice Beach Residences")
    azizi = extract_building_suffix("Azizi Venice 9")
    assert unrelated.master_key != azizi.master_key


def test_none_and_empty_input():
    r = extract_building_suffix(None)
    assert r.master_key == ""
    assert r.building_label is None
    assert r.method == "none"
    r2 = extract_building_suffix("")
    assert r2.master_key == ""


def test_slugify_basic():
    assert slugify("azizi venice") == "azizi-venice"
    assert slugify("Creek Beach") == "creek-beach"


def test_slugify_strips_punctuation_and_collapses():
    assert slugify("Azizi Venice - 15!!") == "azizi-venice-15"
    assert slugify("  multiple   spaces  ") == "multiple-spaces"


def test_slugify_empty_falls_back():
    assert slugify("") == "project"
    assert slugify("   ") == "project"


def test_display_name_from_key_title_cases():
    assert display_name_from_key("azizi venice") == "Azizi Venice"
    assert display_name_from_key("creek beach") == "Creek Beach"
