from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.db import db

router = APIRouter()


@router.get("/developments")
def map_developments(period: str = "90d", con=Depends(db)):
    """Development points with coordinates for markers/clusters. No
    choropleth: no community boundary polygons exist anywhere in the data.
    """
    rows = con.execute(
        """
        SELECT d.id, d.name, d.latitude, d.longitude, a.name AS area_name, d.normalized_status,
               dev.name AS developer_name, d.total_units
        FROM scraped.developments d
        LEFT JOIN scraped.areas a ON d.area_id = a.id
        LEFT JOIN scraped.developers dev ON d.developer_id = dev.id
        WHERE d.latitude IS NOT NULL AND d.longitude IS NOT NULL AND d.is_active = 1
        """
    ).fetchall()

    # Enrich with sales activity where a dim_project match exists.
    activity = dict(
        con.execute(
            """
            SELECT dp.matched_development_id, count(*) FROM fact_sales fs
            JOIN dim_project dp ON fs.project_id = dp.project_id
            WHERE dp.matched_development_id IS NOT NULL AND fs.group_en = 'Sales'
            GROUP BY 1
            """
        ).fetchall()
    )

    return {
        "items": [
            {
                "development_id": r[0], "name": r[1], "lat": r[2], "lng": r[3], "area_name": r[4],
                "status": r[5], "developer_name": r[6], "total_units": r[7],
                "sales_count": activity.get(r[0], 0),
            }
            for r in rows
        ]
    }
