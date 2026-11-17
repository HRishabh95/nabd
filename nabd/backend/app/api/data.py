"""Data API: universe, catalog with freshness, series, refresh jobs, headlines and filings."""

from fastapi import APIRouter, HTTPException, Query

from ..data import refresh, store
from ..data.connectors import edgar, gdelt, gkg
from ..data.universe import BY_SYMBOL, UNIVERSE
from ..jobs import runner

router = APIRouter(prefix="/api/data")


@router.get("/universe")
def universe():
    return {"instruments": [i.as_dict() for i in UNIVERSE],
            "themes": [{"key": t.key, "title": t.title} for t in gkg.THEMES]}


@router.get("/catalog")
def catalog():
    return {"series": store.catalog(), "summary": refresh.catalog_summary(), "refresh": refresh.status()}


@router.get("/series/{series_id}")
def series(series_id: str, start: str | None = None, as_of: float | None = Query(None, description="unix time")):
    src = store.source_of(series_id)
    if not src:
        raise HTTPException(404, f"unknown series {series_id}")
    try:
        df = store.read_series(src, series_id, start, as_of)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    meta = BY_SYMBOL.get(series_id)
    return {"id": series_id, "source": src, "instrument": meta.as_dict() if meta else None,
            "columns": list(df.columns), "rows": df.drop(columns=["first_seen"]).to_dict("records")}


@router.post("/refresh/{source}")
async def refresh_source(source: str):  # async: jobs are tasks on the server's event loop
    try:
        return {"job_id": refresh.start_refresh(source)}
    except KeyError as exc:
        raise HTTPException(404, f"unknown source {source}") from exc


@router.get("/jobs")
def jobs(limit: int = 20):
    return {"jobs": runner.recent(limit)}


@router.get("/jobs/{job_id}")
def job(job_id: str):
    j = runner.get(job_id)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


@router.get("/headlines")
async def headlines(q: str | None = None, theme: str | None = None, limit: int = 25):
    """Headlines from Nabd's own GDELT ingest (last 14 days). For a free-text query with few local matches,
    one polite call to GDELT's search API is tried; it is often rate-limited on shared networks."""
    items = gkg.recent_items(theme, q, limit)
    source = "gdelt-gkg"
    if q and len(items) < 5:
        try:
            more = await gdelt.headlines(q, "2weeks", limit)
            items += [{"url": a["url"], "theme": None, "ts": None, "title": a["title"], "source": a["domain"],
                       "tone": None, "lang": a["language"]} for a in more]
            source = "gdelt-gkg+doc"
        except Exception:
            pass
    return {"query": q, "theme": theme, "source": source, "articles": items[:limit]}


@router.get("/filings/{symbol}")
async def filings(symbol: str):
    try:
        return {"symbol": symbol, "filings": await edgar.filings(symbol), "facts": await edgar.fundamentals(symbol)}
    except edgar.EdgarDisabled as exc:
        raise HTTPException(503, str(exc)) from exc
