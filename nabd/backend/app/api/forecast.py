"""Forecasting API: the Kalman nowcast with and without AI news, against the IMF; runs are background jobs."""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..jobs import runner
from ..ml import registry
from ..ml.forecasting import ai_eval, ai_news, data

router = APIRouter(prefix="/api/forecast")


@router.get("")
def latest():
    out = ai_eval.stored()
    if not out:
        raise HTTPException(404, "No nowcast run yet; start one")
    return {**out, "card": registry.MODELS["nowcast"], "inputs": data.latest_inputs()}


def start_run() -> str:
    async def body(progress):
        out = await asyncio.to_thread(ai_eval.run, progress)
        return {"run_id": out["run_id"], "seconds": out["seconds"]}
    return runner.start("nowcast", "Kalman nowcast, with and without AI news", body, {"source": "forecast"},
                        key="nowcast")


@router.post("/run")
async def post_run():
    return {"job_id": start_run()}


@router.post("/news")
async def post_news():
    """Update the AI news signal (new headlines, LLM labels), then rerun the nowcast."""
    async def body(progress):
        got = await ai_news.update(progress)
        out = await asyncio.to_thread(ai_eval.run, progress)
        return {**got, "run_id": out["run_id"]}
    return {"job_id": runner.start("nowcast", "AI news signal and nowcast", body, {"source": "forecast"},
                                   key="nowcast")}


@router.get("/headlines")
def headlines(month: str = Query(pattern=r"^\d{4}-\d{2}$")):
    """The headlines behind one month of the AI news signal, with the LLM's label for each."""
    items = ai_news.headlines(month)
    rel = [i for i in items if i["relevant"]]
    up, down = sum(i["direction"] > 0 for i in rel), sum(i["direction"] < 0 for i in rel)
    return {"month": month, "headlines": items, "relevant": len(rel), "up": up, "down": down,
            "balance": round(100 * (up - down) / (len(rel) + data.SHRINK), 1) if rel else None}


# ---- explore: switch inputs, and score CBUAE's own model ---------------------------------------------------------

class Inputs(BaseModel):
    target: str = Field("real", pattern="^(non_oil|real)$")
    inputs: list[str] = Field(min_length=1, max_length=20)


@router.get("/inputs")
def input_options():
    """The inputs an analyst can switch, grouped, with which ones each model uses by default."""
    from ..ml.forecasting import kalman
    src = {"portwatch": "IMF PortWatch", "fred": "FRED (St. Louis Fed)", "yahoo": "Yahoo Finance", "gdelt": "GDELT",
           "ai_news": "AI labels of UAE headlines (GDELT)"}
    how = {"logyoy": "% change on a year earlier", "diffyoy": "change on a year earlier", "level": "level"}
    meta = {k: {"source": src.get(v[0], v[0]), "series": v[1], "lag_days": v[5],
                "transform": "diffusion balance (% stronger − % weaker)" if v[3] == "diffusion" else how.get(v[4], v[4])}
            for k, v in data.INDICATORS.items()}
    return {"groups": kalman.OPTIONS, "labels": {k: v[6] for k, v in data.INDICATORS.items()}, "meta": meta,
            "default": {"real": kalman.HARD + kalman.NEWS["kalman_ai"]["real"],
                        "non_oil": kalman.HARD + kalman.NEWS["kalman_ai"]["non_oil"]}}


@router.post("/inputs")
async def try_inputs(body: Inputs):
    from ..ml.forecasting import explore
    return await asyncio.to_thread(explore.with_inputs, body.target, body.inputs)


@router.get("/own/template")
def own_template(target: str = Query("real", pattern="^(non_oil|real)$")):
    from fastapi.responses import PlainTextResponse

    from ..ml.forecasting import explore
    return PlainTextResponse(explore.template(target), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="nabd_nowcast_template_{target}.csv"'})


class Own(BaseModel):
    target: str = Field("real", pattern="^(non_oil|real)$")
    csv: str = Field(min_length=10, max_length=200_000)
    name: str = Field("CBUAE model", max_length=60)


@router.post("/own")
async def own(body: Own):
    from ..ml.forecasting import explore
    try:
        return await asyncio.to_thread(explore.own_model, body.target, body.csv, body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc



# ---- does the news help? -------------------------------------------------------------------------------------------

@router.get("/news-effect")
async def news_effect(target: str = Query("non_oil", pattern="^(non_oil|real)$")):
    from ..core.db import store as kv
    from ..ml.forecasting import explore
    key = f"forecast:replay:{target}"
    replay = kv.get(key) or await asyncio.to_thread(explore.shock_replay, target)
    kv.set(key, replay)
    return {"replay": replay, "placebo": kv.get(f"forecast:placebo:{target}")}


@router.post("/placebo")
async def run_placebo(target: str = Query("non_oil", pattern="^(non_oil|real)$")):
    from ..ml.forecasting import explore

    async def body(progress):
        out = await asyncio.to_thread(explore.placebo, target, 40, 11, progress)
        return {"p_value": out["p_value"], "real_rmse": out["real_rmse"]}
    return {"job_id": runner.start("placebo", f"Placebo test for the news signal ({target})", body,
                                   {"source": "forecast"}, key=f"placebo:{target}")}
