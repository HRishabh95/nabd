"""Overview API: what markets are doing and the news that matters to the teams."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..core.db import store as kv
from ..data import markets
from ..data.connectors import docs, gkg

router = APIRouter(prefix="/api/markets")
FILTERS = ["markets", "oil", "hormuz", "uae_economy", "fed_rates", "gold", "ai_capex"]


@router.get("")
async def snapshot():
    out = await asyncio.to_thread(markets.snapshot)
    return {**out, "refreshed": (kv.get("refresh:markets") or {}).get("ts")}


@router.get("/news")
def news(topic: str | None = None, limit: int = 40):
    """topic: one of FILTERS, "central_banks", or none for everything."""
    limit = max(1, min(limit, 100))
    if topic == "central_banks":
        return {"topic": topic, "articles": [{**d, "theme": "central_banks", "theme_title": d["source"]}
                                             for d in docs.recent(limit)]}
    if topic and topic not in FILTERS:
        raise HTTPException(404, f"unknown topic {topic}")
    return {"topic": topic, "articles": gkg.curated(topic, limit),
            "topics": [{"key": k, "title": gkg.THEME_BY_KEY[k].title} for k in FILTERS],
            "refreshed": (kv.get("refresh:news") or {}).get("ts")}
