from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.analytics.core import estimated_gross_yield, pct_change, resolve_period
from apps.api.db import db

router = APIRouter()

MIN_SALES_SAMPLE = 15
MIN_RENTAL_SAMPLE = 15


def _community_stats(con, start, end):
    return con.execute(
        """
        WITH s AS (
            SELECT da.community_key, da.community_name, count(*) sales_count, median(fs.trans_value_aed) median_price
            FROM fact_sales fs JOIN dim_area da ON fs.area_id = da.area_id
            WHERE fs.instance_date BETWEEN ? AND ? AND fs.group_en = 'Sales' GROUP BY 1, 2
        ), r AS (
            SELECT da.community_key, count(*) rental_count, median(fr.annual_amount_aed) median_rent
            FROM fact_rentals fr JOIN dim_area da ON fr.area_id = da.area_id
            WHERE fr.registration_date BETWEEN ? AND ? GROUP BY 1
        )
        SELECT s.community_key, s.community_name, s.sales_count, s.median_price, COALESCE(r.rental_count, 0), r.median_rent
        FROM s LEFT JOIN r ON s.community_key = r.community_key
        """,
        [start, end, start, end],
    ).fetchall()


@router.get("")
def opportunities(period: str = "90d", con=Depends(db)):
    window = resolve_period(con, period)
    cur = {r[0]: r for r in _community_stats(con, window.current_start, window.current_end)}
    prev = {r[0]: r for r in _community_stats(con, window.previous_start, window.previous_end)}

    high_yield = []
    rising_sales = []
    rent_outpacing_price = []

    for key, (ck, name, sales_count, median_price, rental_count, median_rent) in cur.items():
        y = estimated_gross_yield(median_rent, median_price)
        if y is not None and sales_count >= MIN_SALES_SAMPLE and rental_count >= MIN_RENTAL_SAMPLE:
            high_yield.append({
                "community_key": ck, "community_name": name, "estimated_gross_yield_pct": y,
                "median_price": median_price, "median_rent": median_rent,
                "sales_sample": sales_count, "rental_sample": rental_count,
                "why": f"Estimated gross yield of {y:.1f}% (median rent {median_rent:,.0f} / median price {median_price:,.0f}) based on {sales_count} sales and {rental_count} rentals this period.",
            })

        prev_row = prev.get(key)
        if prev_row and sales_count >= MIN_SALES_SAMPLE:
            prev_sales_count = prev_row[2]
            change = pct_change(sales_count, prev_sales_count)
            if change is not None and change >= 30:
                rising_sales.append({
                    "community_key": ck, "community_name": name, "sales_count": sales_count,
                    "previous_sales_count": prev_sales_count, "change_pct": change,
                    "why": f"Sales transactions rose {change:.0f}% ({prev_sales_count} → {sales_count}) vs the prior {window.label} period.",
                })

            prev_median_rent = prev_row[5]
            prev_median_price = prev_row[3]
            rent_change = pct_change(median_rent, prev_median_rent)
            price_change = pct_change(median_price, prev_median_price)
            if (
                rent_change is not None and price_change is not None
                and rental_count >= MIN_RENTAL_SAMPLE and prev_row[4] >= MIN_RENTAL_SAMPLE
                and rent_change > price_change + 5
            ):
                rent_outpacing_price.append({
                    "community_key": ck, "community_name": name,
                    "rent_change_pct": rent_change, "price_change_pct": price_change,
                    "why": f"Median rent grew {rent_change:.1f}% while median sale price grew {price_change:.1f}% over the same {window.label} comparison — rental demand outpacing price appreciation.",
                })

    high_yield.sort(key=lambda x: x["estimated_gross_yield_pct"], reverse=True)
    rising_sales.sort(key=lambda x: x["change_pct"], reverse=True)
    rent_outpacing_price.sort(key=lambda x: x["rent_change_pct"] - x["price_change_pct"], reverse=True)

    return {
        "period": window.label,
        "methodology": (
            f"All signals require >= {MIN_SALES_SAMPLE} sales and/or >= {MIN_RENTAL_SAMPLE} rental observations in the relevant "
            "window to be surfaced. These are deterministic, calculated observations — not predictions, and not investment advice."
        ),
        "high_yield_high_demand": high_yield[:15],
        "rising_sales_momentum": rising_sales[:15],
        "rental_growth_outpacing_price": rent_outpacing_price[:15],
    }
