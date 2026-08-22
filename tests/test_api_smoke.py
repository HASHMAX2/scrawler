"""End-to-end smoke tests against the real warehouse (data/warehouse.duckdb).
These skip if the warehouse hasn't been built yet (fresh checkout, before
`python scripts/refresh_data.py` has run) rather than failing — building it
takes minutes and pulls in the real DLD CSVs, which is out of scope for a
fast unit-test run.
"""
import pytest
from fastapi.testclient import TestClient

from apps.api.db import WAREHOUSE_PATH

pytestmark = pytest.mark.skipif(not WAREHOUSE_PATH.exists(), reason="warehouse.duckdb not built yet — run scripts/refresh_data.py")


@pytest.fixture(scope="module")
def client():
    from apps.api.main import app
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_overview_shape(client):
    resp = client.get("/api/overview?period=90d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sales"]["count"] > 0
    assert body["rentals"]["count"] > 0
    assert "estimated_gross_yield_pct" in body


def test_communities_list_paginated(client):
    resp = client.get("/api/communities?period=90d&page_size=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 0
    assert len(body["items"]) <= 5


def test_community_detail_jvc(client):
    # s1 = Jumeirah Village Circle, verified during manual data inspection.
    resp = client.get("/api/communities/s1?period=90d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["community_name"] == "Jumeirah Village Circle"
    assert body["sales"]["count"] > 0
    assert body["rentals"]["count"] > 0


def test_community_detail_unknown_key_404s(client):
    resp = client.get("/api/communities/not-a-real-key?period=90d")
    assert resp.status_code == 404


def test_sales_breakdown_shares_sum_close_to_100(client):
    resp = client.get("/api/sales/breakdown?by=community&period=90d&limit=1000")
    body = resp.json()
    total_share = sum(item["share_pct"] for item in body["items"])
    assert 99.0 <= total_share <= 101.0


def test_rentals_demand_matrix_shape(client):
    resp = client.get("/api/rentals/demand-matrix?period=90d&top_n_communities=3")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["matrix"]) == 3
    for row in body["matrix"]:
        assert set(row["values"].keys()) == set(body["bedrooms"])


def test_unit_types_yield_only_present_when_both_sides_exist(client):
    resp = client.get("/api/unit-types?period=90d&community_key=s1")
    body = resp.json()
    for item in body["items"]:
        if item["median_price"] is None or item["median_rent"] is None:
            assert item["estimated_gross_yield_pct"] is None


def test_compare_requires_two_to_five_keys(client):
    resp = client.get("/api/compare?keys=s1")
    assert resp.status_code == 400
    resp = client.get("/api/compare?keys=s1,s42")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


def test_data_quality_summary_shape(client):
    resp = client.get("/api/data-quality")
    assert resp.status_code == 200
    body = resp.json()
    assert "area_match_confidence" in body
    assert "project_match_confidence" in body


def test_explorer_sales_pagination(client):
    resp = client.get("/api/explorer/sales?page_size=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) <= 2
    assert body["total"] > 0


def test_explorer_page_size_capped(client):
    resp = client.get("/api/explorer/sales?page_size=10000")
    assert resp.status_code == 400


def test_map_developments_have_coordinates(client):
    resp = client.get("/api/map/developments")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) > 0
    assert all(item["lat"] is not None and item["lng"] is not None for item in items)


def test_projects_list_and_detail(client):
    resp = client.get("/api/projects?limit=5")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) > 0
    detail = client.get(f"/api/projects/{items[0]['project_id']}")
    assert detail.status_code == 200


def test_developers_list(client):
    resp = client.get("/api/developers?limit=5")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) > 0


def test_search_suggest_master_project_ranks_first(client):
    # Verified during manual data inspection: 16 "Azizi Venice N" towers are
    # persisted as one master project family — the master must rank ahead of
    # its own buildings on an exact-name query (product spec §17).
    resp = client.get("/api/search/suggest?q=Azizi Venice&limit=6")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) > 1
    assert body["items"][0]["kind"] == "master"
    assert body["items"][0]["slug"] == "azizi-venice"
    assert all(item["kind"] == "building" for item in body["items"][1:])


def test_search_suggest_short_query_returns_empty(client):
    resp = client.get("/api/search/suggest?q=a")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_search_suggest_no_match_returns_empty_not_error(client):
    resp = client.get("/api/search/suggest?q=zzzznonexistentproject")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_master_project_detail_aggregates_all_buildings(client):
    resp = client.get("/api/projects/master/azizi-venice?period=90d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["building_count"] == len(body["buildings"]) == 16
    assert body["selected_building"] is None
    # The building-comparison table's sales counts must sum to (at most) the
    # combined KPI count — same underlying rows, just grouped differently.
    assert sum(b["sales_count"] for b in body["building_performance"]) == body["kpis"]["sales"]["count"]


def test_master_project_detail_building_filter_narrows_scope(client):
    all_buildings = client.get("/api/projects/master/azizi-venice?period=90d").json()
    one_building = client.get("/api/projects/master/azizi-venice?period=90d&building_slug=azizi-venice-12").json()
    assert one_building["selected_building"]["slug"] == "azizi-venice-12"
    assert one_building["kpis"]["sales"]["count"] < all_buildings["kpis"]["sales"]["count"]
    assert one_building["kpis"]["sales"]["count"] > 0
    # Building comparison table always shows every building regardless of scope.
    assert len(one_building["building_performance"]) == len(all_buildings["building_performance"]) == 16


def test_master_project_detail_unknown_slug_404s(client):
    resp = client.get("/api/projects/master/not-a-real-project")
    assert resp.status_code == 404


def test_master_project_detail_unknown_building_slug_404s(client):
    resp = client.get("/api/projects/master/azizi-venice?building_slug=not-a-real-building")
    assert resp.status_code == 404
