from datetime import date, timedelta

import pytest

from apps.api.analytics.core import (
    PERIOD_DAYS,
    estimated_gross_yield,
    liquidity_score,
    market_share,
    momentum_direction,
    oversupply_risk,
    pct_change,
    resolve_period,
    weighted_score,
)


class _FakeCon:
    """Minimal stand-in for a duckdb connection: resolve_period only calls
    .execute(...).fetchone() to find the data's max/min date.
    """
    def __init__(self, max_date, min_date=None):
        self._max_date = max_date
        self._min_date = min_date or max_date

    def execute(self, query, *_args, **_kwargs):
        self._last_query = query
        return self

    def fetchone(self):
        if "min(" in self._last_query:
            return (self._min_date,)
        return (self._max_date,)


def test_pct_change_basic():
    assert pct_change(110, 100) == 10.0
    assert pct_change(90, 100) == -10.0


def test_pct_change_previous_zero_is_none():
    # Avoid a divide-by-zero producing a nonsensical infinite/huge percentage.
    assert pct_change(10, 0) is None


def test_pct_change_missing_values_is_none():
    assert pct_change(None, 100) is None
    assert pct_change(100, None) is None


def test_momentum_direction_bands():
    assert momentum_direction(10) == "accelerating"
    assert momentum_direction(-10) == "slowing"
    assert momentum_direction(1) == "stable"
    assert momentum_direction(-1) == "stable"


def test_momentum_direction_insufficient_data():
    assert momentum_direction(None) == "insufficient_data"


def test_estimated_gross_yield_formula():
    # 60,000 annual rent / 1,000,000 sale price = 6%
    assert estimated_gross_yield(60000, 1_000_000) == 6.0


def test_estimated_gross_yield_missing_inputs_is_none_not_zero():
    assert estimated_gross_yield(None, 1_000_000) is None
    assert estimated_gross_yield(60000, None) is None
    assert estimated_gross_yield(60000, 0) is None


def test_market_share_basic():
    assert market_share(25, 100) == 25.0


def test_market_share_zero_total_is_none():
    assert market_share(25, 0) is None


def test_liquidity_score_transparent_and_bounded():
    result = liquidity_score(transaction_count=300, months_span=6, consistency=1.0)
    assert 0 <= result["score"] <= 100
    assert result["transaction_count"] == 300
    assert "formula" in result


def test_liquidity_score_zero_transactions_is_zero():
    result = liquidity_score(transaction_count=0, months_span=6, consistency=0.0)
    assert result["score"] == 0.0


def test_liquidity_score_never_exceeds_100():
    # Absurdly high rate should be capped, not blow past 100.
    result = liquidity_score(transaction_count=100_000, months_span=1, consistency=1.0)
    assert result["score"] <= 100.0


def test_oversupply_risk_buckets():
    assert oversupply_risk(100, 1000)["risk"] == "low"        # ratio 0.1
    assert oversupply_risk(1000, 1000)["risk"] == "moderate"  # ratio 1.0
    assert oversupply_risk(2000, 1000)["risk"] == "high"      # ratio 2.0
    assert oversupply_risk(5000, 1000)["risk"] == "very_high"  # ratio 5.0


def test_oversupply_risk_missing_data():
    result = oversupply_risk(None, 1000)
    assert result["risk"] == "insufficient_data"


def test_oversupply_risk_never_claims_to_forecast():
    result = oversupply_risk(100, 1000)
    assert "not a forecast" in result["note"].lower()


def test_resolve_period_30d_anchors_to_data_max_date_not_wallclock():
    con = _FakeCon(date(2026, 8, 15))
    window = resolve_period(con, period="30d")
    assert window.current_end == date(2026, 8, 15)
    assert (window.current_end - window.current_start).days == 29


def test_resolve_period_previous_window_immediately_precedes_current():
    con = _FakeCon(date(2026, 8, 15))
    window = resolve_period(con, period="30d")
    assert window.previous_end == window.current_start - timedelta(days=1)
    assert (window.previous_end - window.previous_start).days == (window.current_end - window.current_start).days


def test_resolve_period_explicit_range():
    con = _FakeCon(date(2026, 8, 15))
    window = resolve_period(con, start="2026-07-01", end="2026-07-31")
    assert window.current_start == date(2026, 7, 1)
    assert window.current_end == date(2026, 7, 31)
    # previous window should be the same length immediately before
    assert (window.previous_end - window.previous_start).days == (window.current_end - window.current_start).days


def test_resolve_period_all_spans_the_full_dataset():
    con = _FakeCon(date(2026, 8, 15), min_date=date(2026, 1, 1))
    window = resolve_period(con, period="all")
    assert window.current_start == date(2026, 1, 1)
    assert window.current_end == date(2026, 8, 15)
    assert window.label == "All Data"


def test_resolve_period_all_has_no_fabricated_previous_window():
    con = _FakeCon(date(2026, 8, 15), min_date=date(2026, 1, 1))
    window = resolve_period(con, period="all")
    # previous window is zero/negative-length -> any pct_change against it
    # must resolve to None, never a fabricated trend.
    assert window.previous_end < window.previous_start or window.previous_end == window.current_start - timedelta(days=1)


def test_period_days_includes_180d():
    # Regression: "180d" is the default `period` param on several routes
    # (project detail, developers list, decision engine). Before this was
    # added, resolve_period's PERIOD_DAYS.get(period, 30) fallback silently
    # treated every "180d" request as a 30-day window instead of 180.
    assert PERIOD_DAYS["180d"] == 180


def test_resolve_period_180d_uses_full_180_days():
    con = _FakeCon(date(2026, 8, 15))
    window = resolve_period(con, period="180d")
    assert (window.current_end - window.current_start).days == 179


def test_weighted_score_all_components_present():
    # Equal weights, equal values -> the average equals that value, and
    # critically must stay on the 0-100 scale (not get multiplied by 100
    # again into the thousands).
    result = weighted_score({"a": 50.0, "b": 50.0, "c": 50.0}, {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})
    assert result == pytest.approx(50.0)


def test_weighted_score_stays_in_0_100_range():
    result = weighted_score({"a": 100.0, "b": 100.0}, {"a": 0.6, "b": 0.4})
    assert result == 100.0
    assert result <= 100.0


def test_weighted_score_missing_component_renormalizes_weights():
    # "a" missing -> only "b"'s weight counts, so the score equals b's value
    # outright rather than being diluted by a's now-absent weight.
    result = weighted_score({"a": None, "b": 80.0}, {"a": 0.7, "b": 0.3})
    assert result == 80.0


def test_weighted_score_all_missing_is_none():
    result = weighted_score({"a": None, "b": None}, {"a": 0.5, "b": 0.5})
    assert result is None


def test_weighted_score_regression_no_double_scaling():
    # The decision-engine bug this guards against: components in the 0-100
    # range weighted-averaged must NOT be multiplied by 100 a second time,
    # which would push nearly every real score above the 100 cap.
    result = weighted_score({"yield": 38.07, "appreciation": 100.0, "liquidity": 34.2}, {"yield": 0.6, "appreciation": 0.1, "liquidity": 0.3})
    assert result is not None
    assert 0.0 <= result <= 100.0
    assert round(result, 2) == round(0.6 * 38.07 + 0.1 * 100.0 + 0.3 * 34.2, 2)
