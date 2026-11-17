"""Forecasting API: the latest nowcast run, a new run (background job, streamed), and scenarios."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..jobs import runner
from ..ml import registry
from ..ml.forecasting import data, run

router = APIRouter(prefix="/api/forecast")


@router.get("")
def latest():
    out = run.latest()
    if not out:
        raise HTTPException(404, "No nowcast run yet; start one")
    return {**out, "card": registry.MODELS["nowcast"], "inputs": data.latest_inputs()}


def start_run() -> str:
    async def body(progress):
        out = await asyncio.to_thread(run.run, progress)
        return {"run_id": out["run_id"], "seconds": out["seconds"],
                "champion": out["targets"]["non_oil"]["champion"]}
    return runner.start("nowcast", "Nowcast and backtest", body, {"source": "forecast"}, key="nowcast")


@router.post("/run")
async def post_run():
    return {"job_id": start_run()}


class Scenario(BaseModel):
    target: str = Field("non_oil", pattern="^(non_oil|real)$")
    hormuz_ships: float = Field(ge=0, le=200)
    brent: float = Field(ge=10, le=300)


@router.post("/scenario")
async def scenario(s: Scenario):
    return await asyncio.to_thread(run.scenario, s.target, s.hormuz_ships, s.brent)
