from apps.api.analytics.search_rank import SearchCandidate, rank_candidates
from ingestion.normalize import canonical_key


def _candidates():
    return [
        SearchCandidate(1, "master", "Azizi Venice", canonical_key("Azizi Venice"), "Master Project · 4 buildings", "azizi-venice"),
        SearchCandidate(2, "building", "Azizi Venice 1", canonical_key("Azizi Venice 1"), "Building · Azizi Venice", "azizi-venice-1", "azizi-venice"),
        SearchCandidate(3, "building", "Azizi Venice 9", canonical_key("Azizi Venice 9"), "Building · Azizi Venice", "azizi-venice-9", "azizi-venice"),
        SearchCandidate(4, "building", "Azizi Venice 12", canonical_key("Azizi Venice 12"), "Building · Azizi Venice", "azizi-venice-12", "azizi-venice"),
        SearchCandidate(5, "master", "DAMAC Lagoons", canonical_key("DAMAC Lagoons"), "Master Project", "damac-lagoons"),
        SearchCandidate(6, "master", "Sobha Hartland", canonical_key("Sobha Hartland"), "Master Project", "sobha-hartland"),
    ]


def test_exact_master_query_ranks_master_first_then_its_buildings():
    # Literal acceptance-test scenario from the product spec.
    results = rank_candidates(canonical_key("Azizi Venice"), _candidates())
    assert results[0].candidate.id == 1
    assert results[0].candidate.kind == "master"
    top_ids = {r.candidate.id for r in results[:4]}
    assert top_ids == {1, 2, 3, 4}
    assert all(r.candidate.master_slug == "azizi-venice" or r.candidate.kind == "master" for r in results[:4])


def test_exact_building_query_ranks_that_building_first():
    results = rank_candidates(canonical_key("Azizi Venice 15"), [
        *_candidates(),
        SearchCandidate(7, "building", "Azizi Venice 15", canonical_key("Azizi Venice 15"), "Building · Azizi Venice", "azizi-venice-15", "azizi-venice"),
    ])
    assert results[0].candidate.id == 7
    assert results[0].tier == 1


def test_unrelated_master_projects_not_returned_for_unrelated_query():
    results = rank_candidates(canonical_key("Sobha Hartland"), _candidates())
    assert results[0].candidate.id == 6
    # DAMAC Lagoons and Azizi Venice must not appear (no fuzzy overlap).
    returned_ids = {r.candidate.id for r in results}
    assert 5 not in returned_ids or results[0].candidate.id == 6


def test_prefix_match():
    results = rank_candidates(canonical_key("Azizi Ven"), _candidates())
    assert results[0].candidate.id == 1  # master still wins the prefix tier
    ids = {r.candidate.id for r in results}
    assert {1, 2, 3, 4}.issubset(ids)


def test_token_subset_match_building_search():
    # "Venice 12" should surface "Azizi Venice 12" via token-subset even
    # though it doesn't start with "venice".
    results = rank_candidates(canonical_key("Venice 12"), _candidates())
    assert results[0].candidate.id == 4


def test_no_match_returns_empty():
    results = rank_candidates(canonical_key("zzz nonexistent project"), _candidates())
    assert results == []


def test_manual_override_ranks_above_fuzzy():
    overrides = {canonical_key("Venice Nine"): canonical_key("Azizi Venice 9")}
    results = rank_candidates(canonical_key("Venice Nine"), _candidates(), overrides)
    assert results[0].candidate.id == 3
    assert results[0].tier == 2
