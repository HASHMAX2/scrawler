from ingestion.entity_resolution import (
    build_area_candidates,
    build_project_candidates,
    match_name,
    resolve_project,
)
from ingestion.normalize import canonical_key


def test_match_name_exact():
    candidates = {"jumeirah village circle": 1, "dubai marina": 2}
    result = match_name("jumeirah village circle", candidates)
    assert result.matched_id == 1
    assert result.confidence == "exact"
    assert result.score == 100.0


def test_match_name_fuzzy_high_auto_links():
    candidates = {"jumeirah village circle": 1}
    # Small typo/variant — should score high enough to auto-link.
    result = match_name("jumeirah villages circle", candidates)
    assert result.confidence == "fuzzy_high"
    assert result.matched_id == 1


def test_match_name_fuzzy_low_is_not_auto_linked():
    candidates = {"business bay": 1}
    # Deliberately unrelated-ish name that might share some tokens but should
    # not be confidently auto-matched.
    result = match_name("business", candidates)
    assert result.confidence in ("fuzzy_low", "unmatched")
    assert result.matched_id is None


def test_match_name_unmatched_when_no_candidates():
    result = match_name("some area", {})
    assert result.confidence == "unmatched"
    assert result.matched_id is None


def test_match_name_empty_raw_key():
    result = match_name("", {"x": 1})
    assert result.confidence == "unmatched"
    assert result.matched_id is None


def test_match_name_override_takes_priority_over_fuzzy():
    candidates = {"jumeirah village circle": 1}
    overrides = {"jvc": 99}
    result = match_name("jvc", candidates, overrides)
    assert result.matched_id == 99
    assert result.confidence == "exact"


def test_build_area_candidates_includes_also_known_as_aliases():
    scraped_areas = [
        {"id": 1, "name": "Jumeirah Village Circle", "also_known_as": "JVC", "dld_community_name_en": None},
    ]
    candidates = build_area_candidates(scraped_areas, [])
    assert candidates[canonical_key("JVC")] == 1
    assert candidates[canonical_key("Jumeirah Village Circle")] == 1


def test_build_area_candidates_includes_dld_community_name():
    scraped_areas = [
        {"id": 5, "name": "Dubai Marina", "also_known_as": None, "dld_community_name_en": "Marsa Dubai"},
    ]
    candidates = build_area_candidates(scraped_areas, [])
    assert candidates[canonical_key("Marsa Dubai")] == 5


def test_build_area_candidates_sub_communities_resolve_to_parent():
    scraped_areas = []
    scraped_subs = [{"id": 10, "parent_area_id": 3, "name": "JVC District 11"}]
    candidates = build_area_candidates(scraped_areas, scraped_subs)
    assert candidates[canonical_key("JVC District 11")] == 3


def test_resolve_project_prefers_building_over_development():
    # "Azizi Venice Tower 15" should resolve to the *tower's* development_id
    # via the finer-grained building match, and report the matched building.
    dev_candidates = {canonical_key("Azizi Venice"): 100}
    building_candidates = {canonical_key("Azizi Venice Tower 15"): (500, 100)}
    result, building_id = resolve_project(
        canonical_key("Azizi Venice Tower 15"), dev_candidates, building_candidates
    )
    assert result.matched_id == 100
    assert building_id == 500


def test_resolve_project_falls_back_to_development_level():
    dev_candidates = {canonical_key("Azizi Venice"): 100}
    building_candidates = {}
    result, building_id = resolve_project(canonical_key("Azizi Venice"), dev_candidates, building_candidates)
    assert result.matched_id == 100
    assert building_id is None


def test_resolve_project_does_not_merge_master_with_specific_tower():
    # A fuzzy match between a master development and one of its towers must
    # not happen just because the tower's name contains the master's name —
    # exact/high-confidence matching only, never a blind substring merge.
    dev_candidates = {canonical_key("Azizi Venice"): 100}
    building_candidates = {canonical_key("Azizi Venice Tower 15"): (500, 100), canonical_key("Azizi Venice Tower 2"): (501, 100)}
    result, building_id = resolve_project(canonical_key("Azizi Venice Tower 2"), dev_candidates, building_candidates)
    assert building_id == 501
    assert result.matched_id == 100


def test_build_project_candidates_shapes():
    devs = [{"id": 1, "name": "Azizi Venice"}]
    bldgs = [{"id": 10, "development_id": 1, "name": "Azizi Venice Tower 15"}]
    dev_candidates, building_candidates = build_project_candidates(devs, bldgs)
    assert dev_candidates[canonical_key("Azizi Venice")] == 1
    assert building_candidates[canonical_key("Azizi Venice Tower 15")] == (10, 1)
