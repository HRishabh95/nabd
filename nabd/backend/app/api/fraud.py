"""Fraud-network API: latest detection run, a new run (background job), and case details."""

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..jobs import runner
from ..ml import registry
from ..ml.fraud import explain as fx
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




@router.get("/case/{case_id}/note")
def note_cached(case_id: str, account: str | None = None):
    out = run.latest()
    hit = fx.cached(out["run_id"], case_id, account) if out else None
    if not hit:
        raise HTTPException(404, "No note yet")
    return hit


@router.post("/case/{case_id}/note")
async def note(case_id: str, account: str | None = None):
    """An AI investigation note for a detected network, grounded in its transfers (cached per run)."""
    out = run.latest()
    d = await asyncio.to_thread(run.case_detail, "combined", case_id) if out else None
    if not d:
        raise HTTPException(404, "Unknown case")
    if account and account not in d["members"]:
        raise HTTPException(400, "Account is not in this network")
    return await fx.explain(d, out["run_id"], account)


@router.get("/account/{account}")
def account(account: str):
    """Where an account sits: its ML risk score and the detected network it belongs to, if any."""
    out = run.latest()
    if not out:
        raise HTTPException(404, "No detection run yet")
    case = next((c["id"] for c in out["methods"]["combined"]["cases"] if account in c["members"]), None)
    return {"account": account, "risk": out.get("scores", {}).get(account, 0.0), "case": case}


@router.get("/case/{case_id}/facts")
async def facts(case_id: str, account: str | None = None):
    """Exactly what the AI is sent for a note: its instructions and the facts, nothing else."""
    out = run.latest()
    d = await asyncio.to_thread(run.case_detail, "combined", case_id) if out else None
    if not d:
        raise HTTPException(404, "Unknown case")
    text = fx._facts(d, account)
    return {"instructions": fx.RULES, "facts": text, "characters": len(text),
            "withheld": ["Synthetic ground-truth labels (laundering yes or no, ring, typology)",
                         "Customer names, addresses, IDs or any personal data (the data has none: accounts are codes)",
                         "Any account or transfer outside this network beyond the totals shown"]}


# declared last: the more specific /case/{case_id}/note and /facts routes above must match first
@router.get("/case/{method}/{case_id}")
async def case(method: str, case_id: str):
    out = await asyncio.to_thread(run.case_detail, method, case_id)
    if not out:
        raise HTTPException(404, "Unknown case")
    return out
