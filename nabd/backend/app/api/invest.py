"""Investment API: portfolio, models, the idea lifecycle, alerts and memory."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..invest import flow, ideas, monitor
from ..jobs import runner
from ..ml import registry
from ..ml.portfolio import ranker, regime, reserve, risk

router = APIRouter(prefix="/api/invest")
USER = "Investment team"  # single-user POC; roles come with sign-in in the client environment


def _idea(idea_id: str) -> dict:
    idea = ideas.get(idea_id)
    if not idea:
        raise HTTPException(404, f"unknown idea {idea_id}")
    return idea


@router.get("/portfolio")
def portfolio():
    existing = ideas.active_positions()
    r = risk.analyse({}, existing, subject="portfolio")
    return {**reserve.describe(), "risk": r, "regime": regime.regime(),
            "positions": [i for i in ideas.all_ideas() if i["stage"] == "position"]}


@router.get("/models")
def models():
    rk = ranker.latest() or {}
    return {"cards": registry.MODELS, "ranker": {k: rk.get(k) for k in ("run_id", "as_of", "metrics", "importance",
                                                                        "ic_history")},
            "regime": regime.regime(), "recent_runs": {m: registry.latest(m, 5) for m in registry.MODELS}}


@router.get("/runs/{run_id}")
def run(run_id: str):
    r = registry.get(run_id)
    if not r:
        raise HTTPException(404, "unknown run")
    return {**r, "card": registry.MODELS.get(r["model"])}


@router.post("/models/ranker/train")
async def train_ranker():
    import asyncio

    async def body(progress):
        return (await asyncio.to_thread(ranker.train, progress))["metrics"]
    return {"job_id": runner.start("ranker", "Train return-ranking model", body, {}, key="ranker")}


# ---------- ideas ----------
class NewIdea(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    horizon: str = Field(pattern="^(tactical|strategic)$")


@router.get("/ideas")
def list_ideas():
    return {"ideas": ideas.all_ideas(), "stages": ideas.STAGES, "labels": ideas.STAGE_LABELS}


@router.post("/ideas")
async def new_idea(body: NewIdea):
    idea = ideas.create(body.text, body.horizon, USER)
    return {"idea": idea, "job_id": flow.start_parse(idea["id"])}


@router.get("/ideas/{idea_id}")
def get_idea(idea_id: str):
    return {"idea": _idea(idea_id), "events": ideas.events(idea_id)}


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: str, reason: str = ""):
    idea = _idea(idea_id)
    if idea["status"] == "deleted":
        raise HTTPException(409, "Already deleted")
    from ..invest import monitor
    for a in monitor.alerts("open"):
        if a["idea_id"] == idea_id:
            monitor.ack(a["id"], USER)
    return ideas.delete(idea_id, USER, reason)


@router.post("/ideas/{idea_id}/thesis")
def edit_thesis(idea_id: str, thesis: dict):
    _idea(idea_id)
    return {"idea": flow.edit_thesis(idea_id, thesis, USER)}


@router.post("/ideas/{idea_id}/reparse")
async def reparse(idea_id: str):
    _idea(idea_id)
    return {"job_id": flow.start_parse(idea_id)}


@router.get("/ideas/{idea_id}/screen")
async def screen(idea_id: str):  # async: may start the proposal job on the server's event loop
    import asyncio
    if not _idea(idea_id).get("thesis"):
        raise HTTPException(409, "The thesis is not ready yet")
    idea = _idea(idea_id)
    if not idea.get("proposal"):
        return flow.screen(idea_id)
    return await asyncio.to_thread(flow.screen, idea_id)


@router.post("/ideas/{idea_id}/propose")
async def repropose(idea_id: str):
    if not _idea(idea_id).get("thesis"):
        raise HTTPException(409, "The thesis is not ready yet")
    return {"job_id": flow.start_propose(idea_id)}


class BasketItem(BaseModel):
    symbol: str
    weight_pct: float = Field(0, ge=-20, le=10, description="Negative = cut a holding or underweight a name the mandates hold")
    research_only: bool = Field(False, description="Study it in deep research without trading it")


class Basket(BaseModel):
    items: list[BasketItem] = Field(min_length=1, max_length=10)
    funding: str = Field("equity", pattern="^(equity|cash|mandate)$")


def _validate_basket(body: Basket) -> None:
    """The same checks for sending and for previewing a selection."""
    from ..data.universe import BY_SYMBOL
    from ..invest import lookthrough
    from ..invest.screening import holdings
    held = {h["symbol"]: h["weight_pct"] for h in holdings()}
    via = lookthrough.indirect(held)
    unknown = [i.symbol for i in body.items if i.symbol not in BY_SYMBOL]
    if unknown:  # only instruments in Nabd's universe reach the models
        raise HTTPException(422, f"Not in the universe: {', '.join(unknown[:5])}")
    if len({i.symbol for i in body.items}) != len(body.items):
        raise HTTPException(422, "Each instrument can appear once")
    for i in body.items:
        if i.research_only:
            continue
        if i.weight_pct == 0:
            raise HTTPException(422, f"{i.symbol}: weight cannot be zero (mark it research only instead)")
        # a reserve portfolio does not short: a cut can take a name down to zero, counting what the mandates hold
        cap = held.get(i.symbol, 0.0) + via.get(i.symbol, 0.0)
        if i.weight_pct < 0 and -i.weight_pct > cap + 1e-9:
            where = f" ({held.get(i.symbol, 0):.2f}% directly, {via.get(i.symbol, 0):.2f}% through the mandates)" if via.get(i.symbol) else ""
            raise HTTPException(422, f"{i.symbol}: can cut at most {cap:.2f}% (the amount held{where})")


@router.post("/ideas/{idea_id}/basket")
async def basket(idea_id: str, body: Basket):
    _idea(idea_id)
    _validate_basket(body)
    idea = flow.set_basket(idea_id, [i.model_dump() for i in body.items], body.funding, USER)
    return {"idea": idea, "job_id": flow.start_research(idea_id)}


@router.post("/ideas/{idea_id}/preview")
async def preview(idea_id: str, body: Basket):
    """What a selection would do to the portfolio, before anything is saved or run."""
    import asyncio
    idea = _idea(idea_id)
    _validate_basket(body)
    return await asyncio.to_thread(flow.preview, idea, [i.model_dump() for i in body.items], body.funding)


@router.post("/ideas/{idea_id}/use-split")
async def use_split(idea_id: str):
    """Adopt the split that deep research proposed (already checked) as the idea's selection, then refit."""
    import asyncio
    idea = _idea(idea_id)
    split = ((idea.get("research") or {}).get("split") or {}).get("lines") or []
    if not split:
        raise HTTPException(409, "This research has no proposed split")
    body = Basket(items=[BasketItem(symbol=x["symbol"], weight_pct=x["weight_pct"]) if x["weight_pct"]
                         else BasketItem(symbol=x["symbol"], research_only=True) for x in split],
                  funding=idea.get("funding") or "cash")
    _validate_basket(body)
    if not any(i.weight_pct and not i.research_only for i in body.items):
        raise HTTPException(409, "The proposed split trades nothing; keep the current selection or choose lines yourself")
    return await asyncio.to_thread(flow.adopt_split, idea_id, [i.model_dump() for i in body.items], USER)


class ResearchRun(BaseModel):
    as_of: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    web: bool = True


@router.post("/ideas/{idea_id}/research")
async def research(idea_id: str, body: ResearchRun | None = None):
    """Start (or resume) deep research. With as_of, rerun it as it would have looked on that date."""
    idea = _idea(idea_id)
    if not idea.get("basket"):
        raise HTTPException(409, "Select instruments first")
    b = body or ResearchRun()
    return {"job_id": flow.start_research(idea_id, b.as_of, b.web)}


@router.post("/ideas/{idea_id}/fit")
def fit(idea_id: str):
    idea = _idea(idea_id)
    if not idea.get("basket"):
        raise HTTPException(409, "Select instruments first")
    if not flow.trade_lines(idea["basket"]):
        raise HTTPException(409, "Every line is research only: add a line to cut, add or protect before portfolio fit")
    return {"fit": flow.compute_fit(idea_id, USER)}


class Resize(BaseModel):
    multiple: float = Field(gt=0, le=20)


@router.post("/ideas/{idea_id}/resize")
def resize(idea_id: str, body: Resize):
    _idea(idea_id)
    return {"fit": flow.resize(idea_id, body.multiple, USER)}


@router.post("/ideas/{idea_id}/stress")
async def stress(idea_id: str):
    _idea(idea_id)
    return {"job_id": flow.start_stress(idea_id)}


@router.post("/ideas/{idea_id}/committee")
async def committee(idea_id: str):
    idea = _idea(idea_id)
    if not idea.get("stress"):
        raise HTTPException(409, "Run the stress tests first")
    return {"job_id": flow.start_committee(idea_id)}


class ExitPlan(BaseModel):
    target_active_bp: float
    stop_active_bp: float
    review_by: str
    invalidation: list[dict] = []
    rebalance: str = "Unwind to benchmark weights over 5 trading days"


@router.post("/ideas/{idea_id}/exit-plan")
def exit_plan(idea_id: str, body: ExitPlan):
    _idea(idea_id)
    return {"idea": flow.set_exit_plan(idea_id, body.model_dump(), USER)}


class Signoff(BaseModel):
    opinion: str = Field(pattern="^(no objection|objection|conditional)$")
    comment: str = ""
    by: str = "Risk Management"


@router.post("/ideas/{idea_id}/risk-signoff")
def signoff(idea_id: str, body: Signoff):
    if not _idea(idea_id).get("committee"):
        raise HTTPException(409, "Prepare the committee pack first")
    return {"idea": flow.risk_signoff(idea_id, body.opinion, body.comment, body.by)}


class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|reject|defer)$")
    conditions: str = ""
    rationale: str = ""
    by: str = "MRMC"


@router.post("/ideas/{idea_id}/decision")
async def decision(idea_id: str, body: Decision):
    if not _idea(idea_id).get("committee"):
        raise HTTPException(409, "Prepare the committee pack first")
    try:
        idea = flow.decide(idea_id, body.decision, body.conditions, body.rationale, body.by)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if idea["stage"] == "position":
        import asyncio
        try:  # first health check right away; the decision stands even if monitoring fails
            await asyncio.to_thread(monitor.run_once)
        except Exception as exc:
            ideas.log(idea_id, "Nabd monitor", "position", "monitor error", {"error": str(exc)[:200]})
        idea = ideas.get(idea_id)
    return {"idea": idea}


class Close(BaseModel):
    reason: str = Field(min_length=3)


@router.post("/ideas/{idea_id}/close")
async def close(idea_id: str, body: Close):
    _idea(idea_id)
    return {"job_id": flow.close(idea_id, body.reason, USER)}


# ---------- monitoring and memory ----------
@router.get("/alerts")
def list_alerts(status: str | None = None):
    return {"alerts": monitor.alerts(status)}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int):
    monitor.ack(alert_id, USER)
    return {"ok": True}


@router.post("/monitor/run")
async def monitor_run():
    import asyncio
    return await asyncio.to_thread(monitor.run_once)


@router.get("/memory")
def memory(q: str):
    return {"query": q, "results": ideas.search_memory(q)}
