"""Deep research: plan → investigate (parallel workers) → challenge → verify → synthesise. A background job.

State is checkpointed into the idea after each step, so a run interrupted by a restart resumes where it stopped.
Every tool result (including allowlisted web searches) is a numbered evidence item shared by all workers.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Literal

from pydantic import BaseModel, Field

from ..core.bus import bus
from ..core.db import conn
from ..core.db import store as kv
from ..data.connectors import docs
from ..data.universe import BY_SYMBOL
from ..jobs import runner
from ..llm.codex_session import Tool
from ..llm.gateway import gateway
from ..ml.portfolio import reserve
from . import agent, ideas, quant, verify

OFFICIAL_DOMAINS = [
    "federalreserve.gov", "ecb.europa.eu", "boj.or.jp", "bis.org", "imf.org", "worldbank.org", "oecd.org",
    "centralbank.ae", "fcsc.gov.ae", "sec.gov", "opec.org", "iea.org", "eia.gov", "mof.go.jp", "fsa.go.jp",
    "jpx.co.jp", "bankofengland.co.uk", "treasury.gov", "bea.gov", "bls.gov",
]
WORKERS = 3
TOOL_BUDGET = 22          # tool calls per worker
WORKER_TIMEOUT = 480      # seconds per worker turn

RULES = agent.BASE_RULES + (
    " You are part of Nabd's deep-research team. Test claims with data rather than describing them: prefer the "
    "quantitative tools (event_study, conditional_returns, analogs, rolling_beta, relative_performance) over "
    "opinion. Every point must cite evidence ids (E1, E2...) returned by tools. Web search (official sources only) "
    "is for finding URLs: to use what a page says, call read_page on the URL and cite the evidence id it returns. "
    "A figure you cannot cite will be removed by the verifier. Report results that contradict the thesis as "
    "clearly as results that support it."
)


# The planner has no tools by design (the researchers do). It must not tell the committee the tests were not run.
_NOT_RUN = re.compile(r"\b(unavailable|unexecuted|not (?:been )?(?:run|executed)|no evidence ids?|cannot access)\b", re.I)


def clean_framing(text: str) -> str:
    """Drop clauses (split at full stops and semicolons) about tool availability from the plan's framing."""
    parts = [x.strip() for x in re.split(r"(?<=[.;])\s+", text or "") if x.strip()]
    keep = [x for x in parts if not _NOT_RUN.search(x)]
    if not keep:
        return text or ""
    out = " ".join(keep).rstrip(" ;,")
    return out if out.endswith(".") else out + "."


# ---------------------------------------------------------------- schemas
class Hypothesis(BaseModel):
    id: str = Field(description="H1, H2, ...")
    statement: str = Field(description="A testable claim the thesis depends on")
    why_it_matters: str
    test: str = Field(description="How to test it with Nabd's tools and data")


class ResearchPlan(BaseModel):
    framing: str = Field(description="One sentence: what the research must establish for the committee")
    hypotheses: list[Hypothesis] = Field(description="4 to 6 hypotheses, most decisive first")


class Finding(BaseModel):
    id: str
    verdict: Literal["supported", "refuted", "inconclusive"]
    confidence: float = Field(description="0 to 1: how sure the evidence makes you")
    summary: str = Field(description="Two sentences on what the tests showed")
    evidence_for: list[agent.Point]
    evidence_against: list[agent.Point]
    caveats: list[str] = Field(description="Limits of the tests (data frequency, proxies, sample size)")


class RedTeam(BaseModel):
    bear_case: str = Field(description="The strongest case against the idea, in three sentences")
    points: list[agent.Point]
    breaks_if: list[str] = Field(description="Concrete conditions under which the idea loses money")


class Trigger(BaseModel):
    label: str
    series: str | None
    op: Literal[">", "<"] | None
    value: float | None


class HypothesisVerdict(BaseModel):
    id: str
    verdict: Literal["supported", "refuted", "inconclusive"]
    confidence: float
    one_line: str


class SplitLine(BaseModel):
    symbol: str = Field(description="One of the selected names, traded or research-only")
    weight_pct: float = Field(description="Proposed change in % of the portfolio: negative holds less (never more than "
                                          "max_cut_pct), positive adds; 0 leaves it out")
    why: str = Field(description="One sentence tying the size to the findings")


class Synthesis(BaseModel):
    headline: str = Field(description="The research conclusion in one sentence")
    overall: Literal["supports the thesis", "mixed", "does not support the thesis"]
    confidence: float
    summary: str = Field(description="One paragraph for the committee, citing evidence ids")
    hypotheses: list[HypothesisVerdict]
    portfolio_view: str = Field(description="What the findings mean for sizing and implementation against the strategic benchmark "
                                            "and the risk budget, citing evidence ids")
    what_would_change_our_mind: list[str]
    proposed_triggers: list[Trigger] = Field(description="Watchable triggers for the exit plan, using Nabd series "
                                                         "ids where possible")
    open_questions: list[str]
    proposed_split: list[SplitLine] = Field(description="How to split the selection given the evidence: a size for each "
                                                        "selected name (0 to leave it out), within the limits supplied")


# ---------------------------------------------------------------- tools
def tools_for(ev: agent.Evidence, idea: dict, budget: dict) -> list[Tool]:
    base = agent.research_tools(ev, idea)
    basket = [b["symbol"] for b in idea["basket"]["items"]]

    def add(name, args, fn):
        try:
            return ev.add(name, args, fn())
        except Exception as exc:  # the model sees a short error and can adapt
            return ev.add(name, args, {"error": f"{type(exc).__name__}: {exc}"[:300]})

    sym_list = {"type": "array", "items": {"type": "string"}, "description": f"Symbols; the idea's basket is {basket}"}
    extra = [
        Tool("event_study", "Market-adjusted cumulative returns of a basket around events. events: "
             + "; ".join(f"{k} = {v}" for k, v in quant.EVENT_SOURCES.items()) + "; dates = your own list",
             {"type": "object", "properties": {
                 "symbols": sym_list, "events": {"type": "string", "enum": [*quant.EVENT_SOURCES, "dates"]},
                 "direction": {"type": "string", "enum": ["any", "up", "down"]},
                 "dates": {"type": "array", "items": {"type": "string"}}, "benchmark": {"type": "string"},
                 "post": {"type": "integer"}},
              "required": ["symbols", "events", "direction", "dates", "benchmark", "post"], "additionalProperties": False},
             lambda symbols, events, direction="any", dates=None, benchmark="SPY", post=20: add(
                 "event_study", {"symbols": symbols, "events": events, "direction": direction, "benchmark": benchmark},
                 lambda: quant.event_study(symbols, events, direction, dates, 5, max(5, min(post, 60)), benchmark))),
        Tool("conditional_returns", "Forward relative returns of a basket after month-ends when a condition held, "
             "against all other months. series: FRED id, symbol, or regime:stress. change_days 0 = level.",
             {"type": "object", "properties": {
                 "symbols": sym_list, "series": {"type": "string"}, "change_days": {"type": "integer"},
                 "op": {"type": "string", "enum": [">", "<"]}, "threshold": {"type": "number"},
                 "horizon_days": {"type": "integer"}, "benchmark": {"type": "string"}},
              "required": ["symbols", "series", "change_days", "op", "threshold", "horizon_days", "benchmark"],
              "additionalProperties": False},
             lambda symbols, series, change_days, op, threshold, horizon_days=63, benchmark="SPY": add(
                 "conditional_returns", {"symbols": symbols, "series": series, "change_days": change_days, "op": op,
                                         "threshold": threshold, "benchmark": benchmark},
                 lambda: quant.conditional_returns(symbols, series, change_days, op, threshold, horizon_days, benchmark))),
        Tool("analogs", "Past months whose macro state most resembled today's, and the basket's relative return after",
             {"type": "object", "properties": {"symbols": sym_list, "benchmark": {"type": "string"}},
              "required": ["symbols", "benchmark"], "additionalProperties": False},
             lambda symbols, benchmark="SPY": add("analogs", {"symbols": symbols, "benchmark": benchmark},
                                                  lambda: quant.analogs(symbols, 8, 63, benchmark))),
        Tool("rolling_beta", "Stability of a sensitivity over 5 years: rolling beta of a symbol to oil, rates, dollar, "
             "vix, gold, spy or yen",
             {"type": "object", "properties": {"symbol": {"type": "string"},
                                               "factor": {"type": "string", "enum": list(quant.FACTOR_SERIES)}},
              "required": ["symbol", "factor"], "additionalProperties": False},
             lambda symbol, factor: add("rolling_beta", {"symbol": symbol, "factor": factor},
                                        lambda: quant.rolling_beta(symbol, factor))),
        Tool("relative_performance", "The basket against its funding leg: relative returns, drawdown, tracking "
             "volatility, information ratio",
             {"type": "object", "properties": {"symbols": sym_list}, "required": ["symbols"],
              "additionalProperties": False},
             lambda symbols: add("relative_performance", {"symbols": symbols},
                                 lambda: quant.relative_performance(symbols, idea.get("funding") or "equity"))),
        Tool("macro_snapshot", "Latest value and 3-month, 1-year, 3-year changes of a macro series: DGS10, DGS2, "
             "T10YIE, DFEDTARU, ECBDFR, IRLTLT01JPM156N (Japan 10y, monthly), DCOILBRENTEU, DTWEXBGS, DEXJPUS, VIXCLS",
             {"type": "object", "properties": {"series": {"type": "string"}}, "required": ["series"],
              "additionalProperties": False},
             lambda series: add("macro_snapshot", {"series": series}, lambda: quant.macro_snapshot(series))),
        Tool("read_page", "Read an official web page or PDF (central banks, SEC, IMF, OECD, exchanges, regulators) and "
             "get the passages that match your focus terms, with an evidence id you can cite",
             {"type": "object", "properties": {"url": {"type": "string"},
                                               "focus": {"type": "string", "description": "Words or figures to find"}},
              "required": ["url", "focus"], "additionalProperties": False},
             lambda url, focus: _read_page(ev, url, focus)),
        Tool("documents", "Search recent central-bank press releases and speeches (Fed, ECB, Bank of Japan, BIS); "
             "returns passages from the full text of the top matches",
             {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
              "additionalProperties": False},
             lambda query: _documents(ev, query)),
    ]
    out = []
    for t in base + extra:
        out.append(Tool(t.name, t.description, t.parameters, _budgeted(t.fn, budget)))
    return out


def _official(url: str) -> bool:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


async def _read_page(ev: agent.Evidence, url: str, focus: str) -> dict:
    if not _official(url):
        return ev.add("read_page", {"url": url}, {"error": "Not an official source; only allowlisted domains can be read",
                                                 "allowed": OFFICIAL_DOMAINS})
    page = await docs.fetch_text(url)
    terms = [t for t in focus.replace(",", " ").split() if len(t) >= 3]
    passages = docs.passages(page["text"], terms, n=6, width=700) if page["text"] else []
    out = ev.add("read_page", {"url": url, "focus": focus},
                 {"url": url, "kind": page["kind"], "chars": len(page["text"]), "passages": passages,
                  "page": {"url": url, "kind": page["kind"], "text": page["text"][:80000]},
                  **({"error": page["error"]} if page.get("error") else {})})
    # the model gets the passages; the full text stays in the evidence for verification
    return {"evidence_id": out["evidence_id"], "result": {k: v for k, v in out["result"].items() if k != "page"}}


async def _documents(ev: agent.Evidence, query: str) -> dict:
    hits = docs.search(query, _as_of_ts(), 6)
    terms = [t for t in query.split() if len(t) > 3]
    for h in hits[:3]:  # read the top matches in full and keep the passages that match the query
        page = await docs.fetch_text(h["url"])
        h["passages"] = docs.passages(page["text"], terms) if page["text"] else []
        if page.get("error"):
            h["fetch_error"] = page["error"]
    return ev.add("documents", {"query": query}, hits)


def _as_of_ts() -> float | None:
    a = quant.AS_OF.get()
    return time.mktime(time.strptime(a, "%Y-%m-%d")) + 86400 if a else None


def _budgeted(fn, budget: dict):
    async def wrapper(**kw):
        budget["used"] += 1
        if budget["used"] > budget["max"]:
            return {"budget": "Tool budget used up. Write your finding now from the evidence you have."}
        out = fn(**kw)
        if asyncio.iscoroutine(out):
            out = await out
        return out
    return wrapper


# ---------------------------------------------------------------- state
def _save(idea_id: str, state: dict, stage_note: str | None = None):
    state["updated"] = time.time()
    conn().execute("UPDATE ideas SET research=?, updated=? WHERE id=?",
                   (json.dumps(state, default=str), time.time(), idea_id))
    bus.publish("deep.progress", idea_id=idea_id, stage=state.get("stage"), note=stage_note,
                done=[h for h, f in (state.get("findings") or {}).items() if f])
    if stage_note:
        ideas.log(idea_id, "Nabd research", "research", stage_note)


def _relay(idea_id: str, step: str, state: dict):
    def f(kind, data):
        if kind == "tool.start":
            state.setdefault("calls", {}).setdefault(step, 0)
            state["calls"][step] += 1
        payload = {k: v for k, v in data.items() if k != "result"}
        bus.publish(f"agent.{kind}", idea_id=idea_id, step=step, **payload)
    return f


def _context(idea: dict) -> dict:
    existing = ideas.active_positions()
    items = idea["basket"]["items"]
    funding = {"equity": "funded pro rata from the book's gold and commodity lines (a relative bet within the book)",
               "cash": "funded from T-bills in the liquidity sleeve", "mandate": "proceeds of cuts stay in the gold and "
               "commodity lines"}.get(idea.get("funding") or "equity", idea.get("funding"))
    return {"thesis": idea["thesis"], "basket": idea["basket"], "funding": funding,
            # traded lines carry a weight; research-only names are studied and tested at a hypothetical size only
            "traded": {b["symbol"]: b["weight_pct"] for b in items if not b.get("research_only") and b["weight_pct"]},
            "research_only": [b["symbol"] for b in items if b.get("research_only")],
            "names": {b["symbol"]: BY_SYMBOL[b["symbol"]].name for b in idea["basket"]["items"]
                      if b["symbol"] in BY_SYMBOL},
            "portfolio": {"notional_usd_bn": reserve.NOTIONAL_USD_BN, "risk_budget_bp": reserve.ACTIVE_RISK_BUDGET_BP,
                          "approved_ideas": [i["id"] + " " + (i["title"] or "") for i in ideas.all_ideas()
                                             if i["stage"] == "position"],
                          "existing_active_weights_pct": {k: round(v * 100, 3) for k, v in existing.items()}},
            "as_of": quant.AS_OF.get()}


PLAN_TASK = ("Break the thesis into 4-6 testable hypotheses. Say which Nabd tools and data test each one. "
             "Tools: event_study, conditional_returns, analogs, rolling_beta, relative_performance, "
             "macro_snapshot, documents, price_stats, macro_betas, ml_rank, news_search, news_theme, filings, "
             "search_memory, market_regime, plus web search of official sources. You are only planning: "
             "separate researchers run these tools in the next step. Do not run tools, and do not mention "
             "whether tools or evidence are available. The framing is the question the committee needs answered.")


def _plan_key(idea_id: str, items: list[dict]) -> tuple[str, list[str]]:
    return f"research_plan:{idea_id}", sorted(f"{i['symbol']}:{'r' if i.get('research_only') else 't'}" for i in items)


async def preview_plan(idea: dict, items: list[dict], funding: str) -> dict:
    """Run only the planning step for a selection and keep the plan, so the team sees the hypotheses before the
    research runs; the run uses the same plan if the selection has not changed."""
    lines = [{"symbol": i["symbol"], "weight_pct": 0.0 if i.get("research_only") else float(i.get("weight_pct") or 0),
              "research_only": bool(i.get("research_only"))} for i in items]
    ctx = _context({**idea, "basket": {"items": lines}, "funding": funding})
    res = await gateway.run("deep-plan", RULES, json.dumps({"task": PLAN_TASK, **ctx}, indent=1, default=str),
                            schema=ResearchPlan)
    plan = res.parsed.model_dump()
    plan["framing"] = clean_framing(plan["framing"])
    key, sig = _plan_key(idea["id"], lines)
    kv.set(key, {"plan": plan, "selection": sig, "ts": time.time()})
    return plan


# ---------------------------------------------------------------- pipeline
async def run(idea_id: str, progress, as_of: str | None = None, web: bool = True) -> dict:
    if as_of:
        quant.AS_OF.set(as_of)
    idea = ideas.get(idea_id)
    state = idea.get("research") if (idea.get("research") or {}).get("kind") == "deep" else None
    if not state or state.get("stage") == "done" or state.get("as_of") != as_of:
        state = {"kind": "deep", "stage": "plan", "started": time.time(), "as_of": as_of, "web": web,
                 "plan": None, "findings": {}, "red_team": None, "verification": None, "synthesis": None,
                 "evidence": {}, "calls": {}}
    ev = agent.Evidence()
    ev.items = state["evidence"]  # shared, numbered across all workers; persisted with the state
    ctx = _context(idea)
    domains = OFFICIAL_DOMAINS if web else None

    async def on_web(record):
        result = dict(record["result"])
        # A page the model opened: fetch the same official page so its text is part of the evidence
        urls = [x.get("url") for x in result.get("results") or [] if isinstance(x, dict) and x.get("url")]
        if result.get("action") in ("openPage", "findInPage") and urls and _official(urls[0]):
            page = await docs.fetch_text(urls[0])
            result["page"] = {"url": page["url"], "kind": page["kind"], "text": page["text"][:60000],
                              **({"error": page["error"]} if page.get("error") else {})}
        out = ev.add("web_search", record["args"], result)
        record["result"] = {"evidence_id": out["evidence_id"], **record["result"]}
        return record

    # 1. plan
    key, sig = _plan_key(idea_id, idea["basket"]["items"])
    previewed = kv.get(key)
    if not state["plan"] and previewed and previewed.get("selection") == sig:  # the plan the team already saw
        state["plan"] = previewed["plan"]
        kv.set(key, None)  # used once
        _save(idea_id, state, "using the previewed plan")
    if not state["plan"]:
        progress(0, 5, "Planning hypotheses")
        _save(idea_id, state)
        res = await gateway.run("deep-plan", RULES, json.dumps({
            "task": PLAN_TASK,
            **ctx}, indent=1, default=str), schema=ResearchPlan, on_event=_relay(idea_id, "plan", state))
        state["plan"] = res.parsed.model_dump()
        state["plan"]["framing"] = clean_framing(state["plan"]["framing"])
        state["stage"] = "investigate"
        _save(idea_id, state, f"research plan: {len(state['plan']['hypotheses'])} hypotheses")

    # 2. investigate, in parallel
    progress(1, 5, "Investigating hypotheses")
    sem = asyncio.Semaphore(WORKERS)

    async def worker(h: dict):
        if state["findings"].get(h["id"]):
            return
        async with sem:
            budget = {"used": 0, "max": TOOL_BUDGET}
            try:
                res = await gateway.run(
                    "deep-worker", RULES, json.dumps({
                        "task": f"Investigate hypothesis {h['id']} only. Run its tests with the tools, look for "
                                "evidence against it as hard as evidence for it, then return your finding.",
                        "hypothesis": h, **ctx}, indent=1, default=str),
                    schema=Finding, tools=tools_for(ev, idea, budget), on_event=_relay(idea_id, h["id"], state),
                    web_domains=domains, on_web=on_web, timeout_seconds=WORKER_TIMEOUT)
                f = res.parsed.model_dump()
                f["id"] = h["id"]
                f["tool_calls"] = budget["used"]
            except Exception as exc:
                f = {"id": h["id"], "verdict": "inconclusive", "confidence": 0.0, "error": str(exc)[:300],
                     "summary": "The worker did not finish; this hypothesis is untested.", "evidence_for": [],
                     "evidence_against": [], "caveats": ["Worker failed"], "tool_calls": budget["used"]}
            state["findings"][h["id"]] = f
            _save(idea_id, state, f"{h['id']} {f['verdict']}")

    await asyncio.gather(*(worker(h) for h in state["plan"]["hypotheses"]))

    # 3. challenge
    if not state["red_team"]:
        state["stage"] = "challenge"
        progress(2, 5, "Red team: the case against")
        _save(idea_id, state)
        budget = {"used": 0, "max": TOOL_BUDGET}
        res = await gateway.run("deep-redteam", RULES, json.dumps({
            "task": "You are the red team. Build the strongest evidence-based case AGAINST this idea, including "
                    "risks the hypotheses missed (implementation, liquidity at this size, crowding, regime change, "
                    "concentration with approved ideas). Use tools; cite evidence ids.",
            "findings_so_far": {k: {"verdict": v["verdict"], "summary": v["summary"]} for k, v in state["findings"].items()},
            **ctx}, indent=1, default=str), schema=RedTeam, tools=tools_for(ev, idea, budget),
            on_event=_relay(idea_id, "red_team", state), web_domains=domains, on_web=on_web,
            timeout_seconds=WORKER_TIMEOUT)
        state["red_team"] = res.parsed.model_dump()
        _save(idea_id, state, "red team done")

    # 4. verify
    if not state["verification"]:
        state["stage"] = "verify"
        progress(3, 5, "Verifying every claim")
        _save(idea_id, state)
        state["verification"] = await verify.verify(state, ev.items, on_event=_relay(idea_id, "verify", state))
        _save(idea_id, state, f"verification: {state['verification']['stats']['supported']} of "
                              f"{state['verification']['stats']['claims']} claims supported")

    # 5. synthesise
    state["stage"] = "synthesise"
    progress(4, 5, "Writing the report")
    _save(idea_id, state)
    kept = verify.filtered_findings(state)
    res = await gateway.run("deep-synthesis", RULES, json.dumps({
        "task": "Write the deep-research report for the committee from the verified findings. Weigh evidence for "
                "and against honestly; do not recommend approval or rejection. Propose watchable triggers using "
                "Nabd series ids (e.g. DCOILBRENTEU, DGS10, IRLTLT01JPM156N, VIXCLS, regime:stress, news:<theme>, "
                "or a symbol).",
        "plan": state["plan"], "verified_findings": kept, "red_team": state["red_team"],
        "verification_stats": state["verification"]["stats"], "split_limits": split_limits(idea),
        "split_task": "Propose proposed_split: a size for each selected name, traded or research-only. Cuts never "
                      "exceed max_cut_pct; keep the whole idea inside the risk budget; size by the strength of the "
                      "verified evidence; 0 for names the evidence does not support. Nabd recomputes the result.",
        **ctx}, indent=1, default=str),
        schema=Synthesis, on_event=_relay(idea_id, "synthesis", state))
    state["synthesis"] = res.parsed.model_dump()
    state["split"] = check_split(idea, state["synthesis"].get("proposed_split") or [])
    state["stage"] = "done"
    state["finished"] = time.time()
    state["seconds"] = round(state["finished"] - state["started"], 1)
    state["tool_calls"] = sum((f.get("tool_calls") or 0) for f in state["findings"].values())
    _save(idea_id, state, f"deep research done: {state['synthesis']['overall']}")
    ideas.remember(idea_id, "research", f"{state['synthesis']['headline']} {state['synthesis']['summary']}")
    progress(5, 5, "Report ready")
    return {"idea_id": idea_id, "overall": state["synthesis"]["overall"], "evidence": len(ev.items),
            "seconds": state["seconds"]}


def split_limits(idea: dict) -> dict:
    """What the report may propose: each selected name with its current size and the most it can be cut."""
    from . import lookthrough
    from .screening import holdings
    held = {h["symbol"]: h["weight_pct"] for h in holdings()}
    via = lookthrough.indirect(held)
    fit = idea.get("fit") or {}
    return {"names": [{"symbol": b["symbol"], "name": b.get("name"), "selected_pct": b["weight_pct"],
                       "research_only": bool(b.get("research_only")),
                       "max_cut_pct": round(held.get(b["symbol"], 0.0) + via.get(b["symbol"], 0.0), 3)}
                      for b in (idea.get("basket") or {}).get("items", [])],
            "risk_budget_bp": reserve.ACTIVE_RISK_BUDGET_BP, "funding": idea.get("funding"),
            "budget_used_now_pct": (fit.get("budget_used_pct") or {}).get("before")}


def check_split(idea: dict, lines: list[dict]) -> dict:
    """Enforce the limits on the proposed split (selected names only, cuts within holdings, adds up to 10%) and
    recompute what it does to the portfolio. The assistant proposes; Nabd checks."""
    from . import flow
    lim = {n["symbol"]: n for n in split_limits(idea)["names"]}
    out, notes = [], []
    for ln in lines:
        s_ = (ln.get("symbol") or "").upper()
        if s_ not in lim:
            notes.append(f"{s_}: not in the selection, left out")
            continue
        w = float(ln.get("weight_pct") or 0.0)
        if w < -lim[s_]["max_cut_pct"]:
            notes.append(f"{s_}: cut capped at {lim[s_]['max_cut_pct']:.2f}%, the amount held")
            w = -lim[s_]["max_cut_pct"]
        w = round(min(w, 10.0), 3)
        out.append({"symbol": s_, "name": lim[s_]["name"], "weight_pct": w, "why": ln.get("why", ""),
                    "selected_pct": lim[s_]["selected_pct"], "research_only_before": lim[s_]["research_only"]})
    items = [{"symbol": x["symbol"], "weight_pct": x["weight_pct"]} if x["weight_pct"] else {"symbol": x["symbol"], "research_only": True}
             for x in out]
    try:
        check = flow.preview(idea, items, idea.get("funding") or "cash") if items else None
    except Exception as exc:  # noqa: BLE001 - the report still shows the split; the check says why it failed
        check, notes = None, notes + [f"could not compute the portfolio check ({type(exc).__name__})"]
    return {"lines": out, "notes": notes, "check": check}


def start(idea_id: str, as_of: str | None = None, web: bool = True) -> str:
    async def body(progress):
        out = await run(idea_id, progress, as_of, web)
        idea = ideas.get(idea_id)
        if idea["stage"] == "research":
            ideas.update(idea_id, "Nabd", "research complete", stage="fit")
        bus.publish("research.done", idea_id=idea_id, title=idea["title"], overall=out["overall"])
        return out
    label = f"Deep research for {idea_id}" + (f" as of {as_of}" if as_of else "")
    return runner.start("deep_research", label, body, {"idea_id": idea_id, "as_of": as_of},
                        key=f"deep:{idea_id}")


def resume_interrupted():
    """On startup, restart deep research that a previous process left unfinished."""
    for idea in ideas.all_ideas():
        r = idea.get("research") or {}
        if r.get("kind") == "deep" and r.get("stage") not in (None, "done"):
            start(idea["id"], r.get("as_of"), r.get("web", True))

