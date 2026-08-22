"""Pure calculation helpers shared by every router: period resolution,
period-over-period momentum, market share, gross yield, and a liquidity
score — each with an explicit, inspectable formula (never a mystery number)
and an "Insufficient Data" guard below a minimum sample size.

These are unit-tested directly (tests/test_analytics.py) against hand-built
fixtures so financial calculations are not silently wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

MIN_SAMPLE_FOR_MEDIAN = 5
MIN_SAMPLE_FOR_YIELD = 5
MIN_SAMPLE_FOR_MOMENTUM = 5

PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "6m": 182, "1y": 365}


@dataclass
class PeriodWindow:
    current_start: date
    current_end: date
    previous_start: date
    previous_end: date
    label: str


def data_max_date(con: duckdb.DuckDBPyConnection) -> date:
    row = con.execute(
        "SELECT max(d) FROM (SELECT max(instance_date) d FROM fact_sales UNION ALL SELECT max(registration_date) FROM fact_rentals)"
    ).fetchone()
    return row[0] if row and row[0] else date.today()


def data_min_date(con: duckdb.DuckDBPyConnection) -> date:
    row = con.execute(
        "SELECT min(d) FROM (SELECT min(instance_date) d FROM fact_sales UNION ALL SELECT min(registration_date) FROM fact_rentals)"
    ).fetchone()
    return row[0] if row and row[0] else date.today()


def resolve_period(
    con: duckdb.DuckDBPyConnection,
    period: str | None = "30d",
    start: str | None = None,
    end: str | None = None,
) -> PeriodWindow:
    """Anchors "now" to the latest date actually present in the data (this is
    a fixed historical dataset, not a live feed — using wall-clock "today"
    would make every period mostly empty).
    """
    anchor = data_max_date(con)
    if start and end:
        cur_start = date.fromisoformat(start)
        cur_end = date.fromisoformat(end)
        span = (cur_end - cur_start).days + 1
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return PeriodWindow(cur_start, cur_end, prev_start, prev_end, f"{start}..{end}")

    if period == "ytd":
        cur_start = date(anchor.year, 1, 1)
        cur_end = anchor
        span = (cur_end - cur_start).days + 1
        prev_end = cur_start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=span - 1)
        return PeriodWindow(cur_start, cur_end, prev_start, prev_end, "YTD")

    if period == "all":
        cur_start = data_min_date(con)
        cur_end = anchor
        # No meaningful "previous" window exists before the data starts —
        # a zero-length window before cur_start makes every period-over-period
        # comparison correctly resolve to "Insufficient Data" rather than a
        # fabricated trend.
        return PeriodWindow(cur_start, cur_end, cur_start, cur_start - timedelta(days=1), "All Data")

    days = PERIOD_DAYS.get(period or "30d", 30)
    cur_end = anchor
    cur_start = anchor - timedelta(days=days - 1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return PeriodWindow(cur_start, cur_end, prev_start, prev_end, period or "30d")


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100, 2)


def momentum_direction(pct: float | None, flat_band: float = 3.0) -> str:
    """↑ accelerating / → stable / ↓ slowing, with a dead-band so noise
    around 0% doesn't flip-flop between up/down.
    """
    if pct is None:
        return "insufficient_data"
    if pct > flat_band:
        return "accelerating"
    if pct < -flat_band:
        return "slowing"
    return "stable"


def with_confidence(count: int, min_sample: int = MIN_SAMPLE_FOR_MOMENTUM) -> str:
    return "ok" if count >= min_sample else "insufficient_data"


def estimated_gross_yield(median_annual_rent: float | None, median_sale_price: float | None) -> float | None:
    """Gross Yield = Median Annual Rent / Median Sale Price × 100.

    Returns None (not 0) when either side is missing — callers must not
    render None as "0% yield".
    """
    if not median_annual_rent or not median_sale_price:
        return None
    return round((median_annual_rent / median_sale_price) * 100, 2)


def market_share(part: float, total: float) -> float | None:
    if not total:
        return None
    return round((part / total) * 100, 2)


def liquidity_score(transaction_count: int, months_span: float, consistency: float) -> dict:
    """Transparent 0-100 liquidity score. Never presented as a mystery
    number — every input is returned alongside the score so the UI can show
    exactly how it was computed.

    - `monthly_rate` = transactions per month (capped/scaled against a
      reference of 50 tx/month = "very liquid" ceiling for the 0-100 scale).
    - `consistency` = share of months (0-1) in the window that had >=1
      transaction — a project that trades in bursts scores lower than one
      that trades steadily.
    Formula: score = 100 * (0.7 * min(monthly_rate/50, 1) + 0.3 * consistency)
    """
    monthly_rate = transaction_count / months_span if months_span > 0 else 0.0
    rate_component = min(monthly_rate / 50.0, 1.0)
    score = round(100 * (0.7 * rate_component + 0.3 * consistency), 1)
    return {
        "score": score,
        "transaction_count": transaction_count,
        "months_span": round(months_span, 2),
        "monthly_rate": round(monthly_rate, 2),
        "consistency": round(consistency, 2),
        "formula": "100 * (0.7 * min(monthly_rate/50, 1) + 0.3 * consistency)",
    }


def oversupply_risk(incoming_units: int | None, trailing_annualized_demand: float | None) -> dict:
    """Categorical, explicitly non-predictive. ratio = incoming_units /
    trailing_annualized_demand. Buckets are documented thresholds, not a
    trained model.
    """
    if incoming_units is None or trailing_annualized_demand is None:
        return {"risk": "insufficient_data", "ratio": None, "incoming_units": incoming_units, "trailing_annualized_demand": trailing_annualized_demand}
    if trailing_annualized_demand <= 0:
        ratio = None
        risk = "insufficient_data" if incoming_units == 0 else "very_high"
    else:
        ratio = round(incoming_units / trailing_annualized_demand, 2)
        if ratio < 0.5:
            risk = "low"
        elif ratio < 1.5:
            risk = "moderate"
        elif ratio < 3.0:
            risk = "high"
        else:
            risk = "very_high"
    return {
        "risk": risk,
        "ratio": ratio,
        "incoming_units": incoming_units,
        "trailing_annualized_demand": trailing_annualized_demand,
        "note": "Non-predictive: incoming known units relative to trailing observed demand, not a forecast.",
    }


def weighted_score(components: dict[str, float | None], weights: dict[str, float]) -> float | None:
    """Weighted average of already-0-100-scaled component scores, using only
    the weights of components that are actually present (missing components'
    weight is dropped rather than treated as 0, so a candidate missing one
    metric isn't unfairly punished relative to one with all metrics present).

    Returns a value on the same 0-100 scale as the inputs — this is a
    weighted AVERAGE, not a sum, so it must NOT be multiplied by 100 again.
    Returns None if no components are available at all (nothing to score).
    """
    available_weight = sum(weights[k] for k, v in components.items() if v is not None)
    if available_weight == 0:
        return None
    return sum(weights[k] * v for k, v in components.items() if v is not None) / available_weight


def format_aed(value: float | None) -> str:
    if value is None:
        return "N/A"
    v = abs(value)
    sign = "-" if value < 0 else ""
    if v >= 1_000_000_000:
        return f"{sign}AED {v/1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{sign}AED {v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"{sign}AED {v/1_000:.0f}K"
    return f"{sign}AED {v:.0f}"
