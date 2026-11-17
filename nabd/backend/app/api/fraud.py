"""Fraud-network API: latest detection run, a new run (background job), and case details."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..jobs import runner
from ..ml import registry
from ..ml.fraud import run

router = APIRouter(prefix="/api/fraud")


@router.get("")
def latest():
    out = run.latest()
    if not out:
        raise HTTPException(404, "No detection run yet")
    return {**out, "card": registry.MODELS["fraud"]}


class Params(BaseModel):
    hold_min: float = Field(240, ge=10, le=1440, description="Hold window: money in and out within this many minutes")
    flow_min: float = Field(0.7, ge=0.3, le=0.99, description="Out / in must be between this and its inverse")
    min_amount: float = Field(5000, ge=0, le=1_000_000)


def start(params: dict | None = None) -> str:
    async def body(progress):
        out = await asyncio.to_thread(run.run, params, progress)
        return {"run_id": out["run_id"], "seconds": out["seconds"]}
    return runner.start("fraud", "Fraud-network detection", body, {"source": "fraud", **(params or {})}, key="fraud")


@router.post("/run")
async def post_run(p: Params | None = None):
    return {"job_id": start((p or Params()).model_dump())}


@router.get("/case/{method}/{case_id}")
async def case(method: str, case_id: str):
    out = await asyncio.to_thread(run.case_detail, method, case_id)
    if not out:
        raise HTTPException(404, "Unknown case")
    return out
