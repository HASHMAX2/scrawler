"""Declarative registry of known dataset shapes. Adding support for a new CSV
export (a later DLD refresh with extra columns, a new scraper table, etc.)
means adding an entry here — no changes to the detection/staging/warehouse
orchestration code itself.

`header_signature` is the exact set of column names (order-independent) used
to fingerprint an unknown CSV file. Detection requires an exact set match so
a genuinely different schema is never silently misfiled.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    dataset_type: str
    staging_table: str
    header_signature: frozenset[str]
    filename_glob: str  # informational / used by scripts/refresh_data.py to scan


DLD_SALES = DatasetSpec(
    dataset_type="dld_sales",
    staging_table="stg_dld_sales",
    filename_glob="transactions-*.csv",
    header_signature=frozenset({
        "TRANSACTION_NUMBER", "INSTANCE_DATE", "GROUP_EN", "PROCEDURE_EN",
        "IS_OFFPLAN_EN", "IS_FREE_HOLD_EN", "USAGE_EN", "AREA_EN",
        "PROP_TYPE_EN", "PROP_SB_TYPE_EN", "TRANS_VALUE", "PROCEDURE_AREA",
        "ACTUAL_AREA", "ROOMS_EN", "PARKING", "NEAREST_METRO_EN",
        "NEAREST_MALL_EN", "NEAREST_LANDMARK_EN", "TOTAL_BUYER",
        "TOTAL_SELLER", "MASTER_PROJECT_EN", "PROJECT_EN",
    }),
)

DLD_RENTALS = DatasetSpec(
    dataset_type="dld_rentals",
    staging_table="stg_dld_rentals",
    filename_glob="rents-*.csv",
    header_signature=frozenset({
        "REGISTRATION_DATE", "START_DATE", "END_DATE", "VERSION_EN",
        "AREA_EN", "CONTRACT_AMOUNT", "ANNUAL_AMOUNT", "IS_FREE_HOLD_EN",
        "ACTUAL_AREA", "PROP_TYPE_EN", "PROP_SUB_TYPE_EN", "ROOMS",
        "USAGE_EN", "NEAREST_METRO_EN", "NEAREST_MALL_EN",
        "NEAREST_LANDMARK_EN", "PARKING", "TOTAL_PROPERTIES",
        "MASTER_PROJECT_EN", "PROJECT_EN",
    }),
)

REGISTRY: list[DatasetSpec] = [DLD_SALES, DLD_RENTALS]


def detect(header: list[str]) -> DatasetSpec | None:
    header_set = frozenset(h.strip() for h in header)
    for spec in REGISTRY:
        if spec.header_signature == header_set:
            return spec
    return None
