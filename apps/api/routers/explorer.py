from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.db import db

router = APIRouter()

_SALES_FILTERS = {
    "community_key": ("da.community_key = ?", str),
    "canonical_bedroom": ("fs.canonical_bedroom = ?", str),
    "canonical_property_type": ("fs.canonical_property_type = ?", str),
    "is_offplan": ("fs.is_offplan = ?", bool),
    "date_from": ("fs.instance_date >= ?", str),
    "date_to": ("fs.instance_date <= ?", str),
    "min_price": ("fs.trans_value_aed >= ?", float),
    "max_price": ("fs.trans_value_aed <= ?", float),
    "master_slug": ("mp.slug = ?", str),
    "building_slug": ("dp.building_slug = ?", str),
}

_RENTAL_FILTERS = {
    "community_key": ("da.community_key = ?", str),
    "canonical_bedroom": ("fr.canonical_bedroom = ?", str),
    "canonical_property_type": ("fr.canonical_property_type = ?", str),
    "is_renewal": ("fr.is_renewal = ?", bool),
    "date_from": ("fr.registration_date >= ?", str),
    "date_to": ("fr.registration_date <= ?", str),
    "min_rent": ("fr.annual_amount_aed >= ?", float),
    "max_rent": ("fr.annual_amount_aed <= ?", float),
    "master_slug": ("mp.slug = ?", str),
    "building_slug": ("dp.building_slug = ?", str),
}


def _build_where(query_params: dict, spec: dict) -> tuple[str, list]:
    clauses, params = [], []
    for key, (sql, caster) in spec.items():
        value = query_params.get(key)
        if value is None:
            continue
        clauses.append(sql)
        params.append(caster(value) if caster is not bool else value in ("true", "True", "1", True))
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


@router.get("/sales")
def explorer_sales(
    page: int = 1,
    page_size: int = 50,
    community_key: str | None = None,
    canonical_bedroom: str | None = None,
    canonical_property_type: str | None = None,
    is_offplan: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    master_slug: str | None = None,
    building_slug: str | None = None,
    con=Depends(db),
):
    if page_size > 500:
        raise HTTPException(400, "page_size capped at 500")
    qp = {
        "community_key": community_key, "canonical_bedroom": canonical_bedroom,
        "canonical_property_type": canonical_property_type, "is_offplan": is_offplan,
        "date_from": date_from, "date_to": date_to, "min_price": min_price, "max_price": max_price,
        "master_slug": master_slug, "building_slug": building_slug,
    }
    where, params = _build_where(qp, _SALES_FILTERS)
    base = f"""
        FROM fact_sales fs
        JOIN dim_area da ON fs.area_id = da.area_id
        LEFT JOIN dim_project dp ON fs.project_id = dp.project_id
        LEFT JOIN dim_master_project mp ON dp.master_project_id = mp.master_project_id
        WHERE 1=1 {where}
    """
    total = con.execute(f"SELECT count(*) {base}", params).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT fs.sale_id, fs.instance_date, da.community_name, dp.dld_project_name, fs.canonical_property_type,
               fs.canonical_bedroom, fs.trans_value_aed, fs.area_sqm, fs.price_per_sqft_aed, fs.is_offplan
        {base} ORDER BY fs.instance_date DESC LIMIT ? OFFSET ?
        """,
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    cols = ["sale_id", "instance_date", "community", "project", "property_type", "bedroom", "price", "area_sqm", "price_per_sqft", "is_offplan"]
    return {
        "page": page, "page_size": page_size, "total": total,
        "items": [dict(zip(cols, (r[0], r[1].isoformat() if r[1] else None, *r[2:]))) for r in rows],
    }


@router.get("/rentals")
def explorer_rentals(
    page: int = 1,
    page_size: int = 50,
    community_key: str | None = None,
    canonical_bedroom: str | None = None,
    canonical_property_type: str | None = None,
    is_renewal: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_rent: float | None = None,
    max_rent: float | None = None,
    master_slug: str | None = None,
    building_slug: str | None = None,
    con=Depends(db),
):
    if page_size > 500:
        raise HTTPException(400, "page_size capped at 500")
    qp = {
        "community_key": community_key, "canonical_bedroom": canonical_bedroom,
        "canonical_property_type": canonical_property_type, "is_renewal": is_renewal,
        "date_from": date_from, "date_to": date_to, "min_rent": min_rent, "max_rent": max_rent,
        "master_slug": master_slug, "building_slug": building_slug,
    }
    where, params = _build_where(qp, _RENTAL_FILTERS)
    base = f"""
        FROM fact_rentals fr
        JOIN dim_area da ON fr.area_id = da.area_id
        LEFT JOIN dim_project dp ON fr.project_id = dp.project_id
        LEFT JOIN dim_master_project mp ON dp.master_project_id = mp.master_project_id
        WHERE 1=1 {where}
    """
    total = con.execute(f"SELECT count(*) {base}", params).fetchone()[0]
    rows = con.execute(
        f"""
        SELECT fr.rental_id, fr.registration_date, da.community_name, dp.dld_project_name, fr.canonical_property_type,
               fr.canonical_bedroom, fr.annual_amount_aed, fr.area_sqm, fr.rent_per_sqft_aed, fr.is_renewal
        {base} ORDER BY fr.registration_date DESC LIMIT ? OFFSET ?
        """,
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    cols = ["rental_id", "registration_date", "community", "project", "property_type", "bedroom", "annual_rent", "area_sqm", "rent_per_sqft", "is_renewal"]
    return {
        "page": page, "page_size": page_size, "total": total,
        "items": [dict(zip(cols, (r[0], r[1].isoformat() if r[1] else None, *r[2:]))) for r in rows],
    }
