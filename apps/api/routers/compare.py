from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.db import db
from apps.api.routers.communities import community_detail

router = APIRouter()


@router.get("")
def compare_communities(keys: str, period: str = "90d", con=Depends(db)):
    """`keys` is a comma-separated list of 2-5 community_key values."""
    community_keys = [k.strip() for k in keys.split(",") if k.strip()]
    if not (2 <= len(community_keys) <= 5):
        raise HTTPException(400, "Provide 2-5 community_key values (comma-separated)")
    return {"period": period, "items": [community_detail(ck, period, con) for ck in community_keys]}
