"""Ask Nabd: a conversational analyst over Nabd's data, models, ideas and documents.

- Codex answers by calling Nabd's tools; every figure must come from a tool result (a numbered evidence item).
- Arithmetic goes through the `calc` tool, so derived figures are evidence too.
- Charts: the model only chooses which evidence to plot and how; the backend builds the chart from the tool's
  own data (at most 4 series, one axis). The model never writes a data point.
- After the answer, every figure in the text is traced to its cited evidence (the deep-research checker).
- Each question runs as a background job; tool calls and the answer text stream to the page.
"""

from __future__ import annotations

import ast
import json
import operator
import re
import time
import uuid
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..core.bus import bus
from ..core.db import conn
from ..data import store
from ..invest import agent, deep, ideas, monitor, quant, verify
from ..jobs import runner
from ..llm.codex_session import Tool
from ..llm.gateway import gateway
from ..ml import registry
from ..ml.portfolio import ranker, regime, reserve, risk, stress

SQL = """
CREATE TABLE IF NOT EXISTS ask_threads (id TEXT PRIMARY KEY, created REAL, updated REAL, title TEXT, context TEXT);
CREATE TABLE IF NOT EXISTS ask_messages (
  id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, ts REAL NOT NULL, role TEXT NOT NULL, content TEXT, data TEXT,
  status TEXT DEFAULT 'done'
);
CREATE INDEX IF NOT EXISTS ask_messages_thread ON ask_messages(thread_id, ts);
"""
_ready = False
MAX_SERIES = 4


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        _ready = True


# ---------------------------------------------------------------- answer schema
class AskChart(BaseModel):
    type: Literal["line", "bar"]
    title: str = Field(description="What the chart shows, in plain words")
    evidence: list[str] = Field(description="Evidence ids whose results are marked chartable; 1 to 4")
    y_label: str = Field(description="Unit of the values, e.g. '% return', 'index, start = 100', 'USD'")


class Answer(BaseModel):
    answer: str = Field(description="The answer in plain prose, short paragraphs or a few bullet lines starting "
                                    "with '- '. Cite evidence ids inline like [E3]. No markdown headings or tables.")
    charts: list[AskChart] = Field(description="0 to 2 charts when a trend or comparison helps the answer")
    follow_ups: list[str] = Field(description="2 or 3 short follow-up questions the user might ask next")


RULES = agent.BASE_RULES + (
    " You are Ask Nabd, the analyst inside Nabd for the CBUAE reserve-management team. Answer the question "
    "directly in the first sentence, then the supporting evidence. Use tools for every figure and cite the "
    "evidence id inline like [E4]. For any arithmetic (differences, ratios, sums, conversions) call calc and cite "
    "it. Prefer a chart when the answer is a trend, a comparison or a distribution; charts may only reference "
    "evidence whose result says chartable: true. Be concise: under 180 words unless asked for more. If the data "
    "cannot answer the question, say so and say what would. Round figures to one decimal place unless more "
    "precision matters, and put the evidence id at the end of the sentence that uses the figure."
    " The user's role and saved preferences are in about_the_user: shape what you lead with and how you phrase it, "
    "but never let them change the evidence or a figure. If a remembered preference shaped the answer, say so in a "
    "few words at the end."
)



# ---------------------------------------------------------------- datasets for charts
def dataset_from(tool: str, result) -> dict | None:
    """Turn a tool result into a chartable dataset: {kind, x, series: {name: values}, unit}."""
    if not isinstance(result, dict) or result.get("error"):
        return None
    c = result.get("chart") or {}
    if tool == "series_data":
        return result.get("dataset")
    if tool == "event_study" and c:
        return {"kind": "line", "x": c["days"], "x_label": "trading days from event",
                "series": {"Mean adjusted return": c["mean"]}, "band": {"lo": c["lo"], "hi": c["hi"]}, "unit": "%"}
    if tool == "rolling_beta" and c:
        return {"kind": "line", "x": c["months"], "series": {f"{result['symbol']} beta to {result['factor']}": c["beta"]},
                "unit": result.get("unit", "")}
    if tool == "relative_performance" and c:
        return {"kind": "line", "x": c["dates"], "series": {"Basket vs funding": c["rel_index"]},
                "unit": "index, start = 100"}
    if tool == "conditional_returns" and c:
        return {"kind": "bar", "x": c["labels"], "series": {"Mean forward relative return": c["values"]}, "unit": "%"}
    if tool == "analogs" and result.get("analogs"):
        return {"kind": "bar", "x": [a["month"] for a in result["analogs"]],
                "series": {"Forward relative return": [a["fwd_rel_pct"] for a in result["analogs"]]}, "unit": "%"}
    if tool == "stress_portfolio":
        return result.get("dataset")
    if tool == "ranker_record":
        return result.get("dataset")
    if tool in ("regime_history", "nowcast", "fraud_summary"):
        return result.get("dataset")
    return None


class AskEvidence(agent.Evidence):
    """Evidence that also keeps a chartable dataset, and tells the model which results it can plot."""

    def add(self, tool: str, args: dict, result) -> dict:
        ds = dataset_from(tool, result)
        out = super().add(tool, args, result)
        if ds:
            self.items[out["evidence_id"]]["dataset"] = ds
            slim = {k: v for k, v in result.items() if k not in ("chart", "dataset")} if isinstance(result, dict) else result
            return {"evidence_id": out["evidence_id"], "chartable": True, "result": slim}
        return out


# ---------------------------------------------------------------- extra tools
SAFE_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Mod: operator.mod}


def calc(expression: str) -> dict:
    """Evaluate plain arithmetic safely (numbers, + - * / ** %, parentheses, abs, round, min, max)."""
    funcs = {"abs": abs, "round": round, "min": min, "max": max}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in SAFE_OPS:
            return SAFE_OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in SAFE_OPS:
            return SAFE_OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in funcs:
            return funcs[n.func.id](*[ev(a) for a in n.args])
        raise ValueError("only arithmetic is allowed")
    value = ev(ast.parse(expression.replace("^", "**"), mode="eval"))
    return {"expression": expression, "value": round(float(value), 6)}


def series_data(series: list[str], start: str | None = None, transform: str = "level") -> dict:
    """Up to 4 series (symbols, FRED ids, news:<theme>) from a start date: level, index (start = 100) or 12-month
    change. Returns summary statistics and a chartable dataset (weekly points)."""
    frames, stats = {}, {}
    for sid in series[:MAX_SERIES]:
        src = store.source_of(sid)
        if not src:
            stats[sid] = {"error": "unknown series"}
            continue
        df = store.read_series(src, sid).set_index("date")
        col = "adjclose" if "adjclose" in df else ("volume" if src == "gdelt" else "value")
        s = quant._cut(df[[col]])[col].dropna()
        if start:
            s = s[s.index >= pd.Timestamp(start)]
        if s.empty:
            stats[sid] = {"error": "no data in range"}
            continue
        if transform == "index":
            s = s / s.iloc[0] * 100
        elif transform == "yoy":
            s = (s / s.shift(252 if src == "yahoo" else 12 if len(s) < 400 else 252) - 1) * 100
            s = s.dropna()
        frames[sid] = s
        stats[sid] = {"first_date": str(s.index[0].date()), "first": round(float(s.iloc[0]), 3),
                      "last_date": str(s.index[-1].date()), "last": round(float(s.iloc[-1]), 3),
                      "min": round(float(s.min()), 3), "max": round(float(s.max()), 3),
                      "change": round(float(s.iloc[-1] - s.iloc[0]), 3)}
    if not frames:
        return {"error": "no series could be read", "stats": stats}
    names = {r["id"]: r["title"] for r in store.catalog()}

    def label(sid: str) -> str:  # readable series names for the chart: "Brent crude", "US Treasury 10-year yield"
        t = names.get(sid) or sid
        if store.source_of(sid) == "yahoo":
            return sid
        return re.sub(r"^News: ", "News · ", t.split(",")[0])[:28]
    frames = {label(k): v for k, v in frames.items()}
    wide = pd.DataFrame(frames).sort_index().ffill()
    weekly = wide.resample("W-FRI").last().dropna(how="all")
    unit = {"index": "index, start = 100", "yoy": "% change over 12 months"}.get(transform, "level")
    return {"transform": transform, "stats": stats,
            "dataset": {"kind": "line", "x": [str(d.date()) for d in weekly.index],
                        "series": {c: [None if pd.isna(v) else round(float(v), 3) for v in weekly[c]] for c in weekly},
                        "unit": unit}}


def portfolio_overview() -> dict:
    existing = ideas.active_positions()
    r = risk.analyse({}, existing, subject="ask")
    reg = regime.regime()
    return {"notional_usd_bn": reserve.NOTIONAL_USD_BN, "note": "notional, illustrative; not CBUAE's holdings",
            "tranches": reserve.describe()["tranches"], "active_risk_budget_bp": reserve.ACTIVE_RISK_BUDGET_BP,
            "tracking_error_bp": r["te_bp"]["before"], "budget_used_pct": r["budget_used_pct"]["before"],
            "risk_contributions": r["contributions"][:6], "portfolio_var99_1d_pct": r["total_var99_1d_pct"],
            "var_backtest": r["var_backtest"], "risk_run": r["run_id"],
            "regime": {"state": reg["state"], "probabilities": reg["current"], "as_of": reg["as_of"]},
            "monitored_ideas": [{"id": i["id"], "title": i["title"], "basket_pct": (i["basket"] or {}).get("total_pct"),
                                 "health": ((i["position"] or {}).get("health") or {}).get("score")}
                                for i in ideas.all_ideas() if i["stage"] == "position"]}


def ideas_list() -> list[dict]:
    return [{"id": i["id"], "title": i["title"], "stage": i["stage_label"], "horizon": i["horizon"],
             "basket": [b["symbol"] for b in (i["basket"] or {}).get("items", [])],
             "decision": ((i["committee"] or {}).get("decision") or {}).get("decision"),
             "health": ((i["position"] or {}).get("health") or {}).get("score")} for i in ideas.all_ideas()]


def idea_detail(idea_id: str) -> dict:
    i = ideas.get(idea_id)
    if not i:
        return {"error": f"no idea {idea_id}"}
    r, f, s = i.get("research") or {}, i.get("fit") or {}, i.get("stress") or {}
    syn = r.get("synthesis") or {}
    return {
        "id": i["id"], "title": i["title"], "stage": i["stage_label"], "thesis": (i["thesis"] or {}).get("summary"),
        "invalidation": (i["thesis"] or {}).get("invalidation"), "basket": (i["basket"] or {}).get("items"),
        "research": {"headline": syn.get("headline"), "overall": syn.get("overall"), "confidence": syn.get("confidence"),
                     "hypotheses": syn.get("hypotheses"), "bear_case": (r.get("red_team") or {}).get("bear_case"),
                     "verification": (r.get("verification") or {}).get("stats")} if syn else
        {"summary": (r.get("note") or {}).get("summary")},
        "fit": {k: f.get(k) for k in ("te_bp", "budget_used_pct", "max_total_pct", "liquidity", "run_id")} if f else None,
        "stress": {"worst": s.get("worst"), "replays": [{k: x[k] for k in ("name", "active_bp")} for x in s.get("replays", [])],
                   "run_id": s.get("run_id")} if s else None,
        "committee": {"decision": ((i["committee"] or {}).get("decision")), "risk_signoff": (i["committee"] or {}).get("risk_signoff")}
        if i.get("committee") else None,
        "exit_plan": i.get("exit_plan"), "health": (i.get("position") or {}).get("health"),
    }


def stress_portfolio() -> dict:
    """Whole notional portfolio, including approved ideas, under the replays and shocks."""
    existing = ideas.active_positions()
    out = stress.run(existing, "ask", 7)
    rows = out["replays"] + out["shocks"]
    return {"scenarios": [{"name": x["name"], "portfolio_pct": x["portfolio_pct"],
                           "approved_ideas_active_bp": x["active_bp"]} for x in rows], "run_id": out["run_id"],
            "dataset": {"kind": "bar", "x": [x["name"] for x in rows],
                        "series": {"Whole portfolio": [x["portfolio_pct"] for x in rows]}, "unit": "% return"}}


def ranker_record() -> dict:
    rk = ranker.latest() or {}
    h = rk.get("ic_history") or []
    return {"metrics": rk.get("metrics"), "as_of": rk.get("as_of"), "run_id": rk.get("run_id"),
            "importance": rk.get("importance"), "card": registry.MODELS["ranker"],
            "dataset": {"kind": "bar", "x": [x["date"][:7] for x in h[-36:]],
                        "series": {"Monthly rank IC": [x["ic"] for x in h[-36:]]}, "unit": "rank correlation"}}


def regime_history() -> dict:
    r = regime.regime()
    h = r["history"]
    return {"current": r["current"], "state": r["state"], "as_of": r["as_of"], "run_id": r["run_id"],
            "stress_in_episodes": r["metrics"]["stress_in_episodes"],
            "dataset": {"kind": "line", "x": [x["date"] for x in h],
                        "series": {"Stress probability": [x["stress"] for x in h]}, "unit": "probability"}}


def nowcast_view(target: str = "non_oil") -> dict:
    from ..ml.forecasting import ai_eval
    out = ai_eval.stored()
    if not out:
        return {"error": "no nowcast run yet"}
    t = out["targets"][target]
    fc = t["forecast"]
    return {"target": t["label"], "pending_quarter": t["pending"], "current_quarter": t["current"],
            "method": "Kalman state-space nowcast; kalman = hard data only, kalman_ai = hard data plus AI news signals",
            "latest": {q: {v: {k: m[k] for k in ("value", "band70")} for v, m in lq["models"].items()
                           if v in ai_eval.SHOWN} for q, lq in t["latest"].items()},
            "backtest_scores": [s for s in t["backtest"]["scores"] if s["model"] in ai_eval.SHOWN + ["benchmark"]],
            "full_year": [{"year": a["year"], "models": {v: m["value"] for v, m in a["models"].items()},
                           "imf": [{"vintage": i["vintage"], "value": i["value"]} for i in a["imf"]]}
                          for a in t["annual"]],
            "last_official": t["released"][-1] if t["released"] else None, "run_id": out["run_id"],
            "dataset": {"kind": "line", "x": [p["quarter"] for p in fc["kalman_ai"] or fc["kalman"]],
                        "series": {ai_eval.kalman.VARIANTS[v]: [p["value"] for p in fc[v]] for v in ai_eval.SHOWN
                                   if fc.get(v)}, "unit": "% y/y"}}


def fraud_summary() -> dict:
    from ..ml.fraud import run as fr
    out = fr.latest()
    if not out:
        return {"error": "no detection run yet"}
    ms = {**out.get("benchmarks", {}), **out["methods"]}
    return {"data": out["data"], "params": out["params"], "run_id": out["run_id"],
            "methods": {k: {"label": v["label"], **{x: v["eval"][x] for x in ("precision", "recall", "f1", "cases",
                                                                              "rings_whole", "rings_fragmented", "false_alarms")}}
                        for k, v in ms.items()},
            "top_cases_combined": [{k: c[k] for k in ("id", "size", "banks", "flow_aed", "median_hold_min", "score")}
                                   for c in ms["combined"]["cases"][:5]],
            "dataset": {"kind": "bar", "x": [v["label"] for v in ms.values()],
                        "series": {"Alerts to open": [v["eval"]["cases"] for v in ms.values()]}, "unit": "cases"}}


def tools(ev: AskEvidence) -> list[Tool]:
    dummy = {"id": None, "funding": "equity", "basket": {"items": []}}
    out = [t for t in deep.tools_for(ev, dummy, {"used": 0, "max": 40})]

    def add(name, args, fn):
        try:
            return ev.add(name, args, fn())
        except Exception as exc:
            return ev.add(name, args, {"error": f"{type(exc).__name__}: {exc}"[:300]})

    none = {"type": "object", "properties": {}, "additionalProperties": False}
    out += [
        Tool("calc", "Arithmetic on figures from evidence (e.g. '285 - 231', '(48.1 - 11.6)', '2394.6 / 3.6725')",
             {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"],
              "additionalProperties": False}, lambda expression: add("calc", {"expression": expression}, lambda: calc(expression))),
        Tool("series_data", "Up to 4 time series (symbols, FRED ids like DCOILBRENTEU DGS10 VIXCLS IRLTLT01JPM156N, or "
             "news:<theme>) from a start date (YYYY-MM-DD), as level, index (start = 100) or yoy; chartable",
             {"type": "object", "properties": {"series": {"type": "array", "items": {"type": "string"}},
                                               "start": {"type": "string"},
                                               "transform": {"type": "string", "enum": ["level", "index", "yoy"]}},
              "required": ["series", "start", "transform"], "additionalProperties": False},
             lambda series, start, transform="level": add("series_data", {"series": series, "start": start, "transform": transform},
                                                          lambda: series_data(series, start, transform))),
        Tool("portfolio_overview", "The notional reserve portfolio: tranches, tracking error and risk-budget use, "
             "risk contributions, VaR, regime and monitored ideas", none,
             lambda: add("portfolio_overview", {}, portfolio_overview)),
        Tool("ideas_list", "All investment ideas with stage, basket, decision and health", none,
             lambda: add("ideas_list", {}, ideas_list)),
        Tool("idea_detail", "One idea in depth: thesis, research verdict, fit, stress, committee, exit plan, health",
             {"type": "object", "properties": {"idea_id": {"type": "string"}}, "required": ["idea_id"],
              "additionalProperties": False}, lambda idea_id: add("idea_detail", {"idea_id": idea_id}, lambda: idea_detail(idea_id))),
        Tool("alerts", "Open monitoring alerts", none, lambda: add("alerts", {}, lambda: monitor.alerts("open"))),
        Tool("stress_portfolio", "The whole notional portfolio, with approved ideas, under historical replays and "
             "factor shocks (Hormuz, oil collapse, rates +100 bp, risk-off); chartable", none,
             lambda: add("stress_portfolio", {}, stress_portfolio)),
        Tool("ranker_record", "The return-ranking model's out-of-sample record and feature importance; chartable",
             none, lambda: add("ranker_record", {}, ranker_record)),
        Tool("nowcast", "The UAE GDP nowcast (non_oil or real) from a Kalman state-space model, with and without AI "
             "news signals: latest values with bands, quarterly forecasts, full-year growth against the IMF, "
             "pseudo real-time backtest scores, last official release; chartable",
             {"type": "object", "properties": {"target": {"type": "string", "enum": ["non_oil", "real"]}},
              "required": ["target"], "additionalProperties": False},
             lambda target="non_oil": add("nowcast", {"target": target}, lambda: nowcast_view(target))),
        Tool("fraud_summary", "Fraud-network detection: methods compared against labels (precision, recall, rings "
             "caught whole, alerts to open), data description and top cases; chartable", none,
             lambda: add("fraud_summary", {}, fraud_summary)),
        Tool("regime_history", "Market regime probabilities over the last 3 years and in past episodes; chartable",
             none, lambda: add("regime_history", {}, regime_history)),
    ]
    return out


# ---------------------------------------------------------------- charts
def build_charts(specs: list[dict], evidence: dict) -> list[dict]:
    charts = []
    for spec in specs[:2]:
        sets = [(e, evidence[e]["dataset"]) for e in spec["evidence"] if e in evidence and evidence[e].get("dataset")]
        if not sets:
            continue
        if len(sets) == 1:
            eid, ds = sets[0]
            series = [{"name": n, "values": v} for n, v in list(ds["series"].items())[:MAX_SERIES]]
            charts.append({"type": ds["kind"],  # the data's shape decides: a time series is a line, categories bars
                           "title": spec["title"], "y_label": spec["y_label"] or ds.get("unit", ""), "x": ds["x"],
                           "x_label": ds.get("x_label"), "series": series, "band": ds.get("band"), "evidence": [eid]})
            continue
        # several datasets: merge series on a shared x (union, in order)
        xs: list = []
        for _, ds in sets:
            for x in ds["x"]:
                if x not in xs:
                    xs.append(x)
        if all(isinstance(x, str) and re.match(r"\d{4}-\d{2}", str(x)) for x in xs):
            xs.sort()
        series = []
        for eid, ds in sets:
            pos = {x: i for i, x in enumerate(ds["x"])}
            for name, vals in ds["series"].items():
                if len(series) >= MAX_SERIES:
                    break
                series.append({"name": name, "values": [vals[pos[x]] if x in pos else None for x in xs]})
        charts.append({"type": sets[0][1]["kind"], "title": spec["title"], "y_label": spec["y_label"], "x": xs,
                       "series": series, "evidence": [e for e, _ in sets]})
    return charts


MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATES = re.compile(rf"\b\d{{1,2}}\s+{MONTHS}\b|\b{MONTHS}\s+\d{{1,2}}\b|\b\d{{4}}-\d{{2}}(?:-\d{{2}})?\b")
CITE = re.compile(r"\[?E\d+(?:\s*[,–-]\s*E\d+)*\]?")


def figure_check(text: str, evidence: dict) -> dict:
    """Trace every figure in the answer to the evidence cited in the same paragraph or bullet (falling back to all
    evidence cited in the answer). Dates are not figures."""
    all_ids = re.findall(r"E\d+", text)
    total, untraced = 0, []
    for block in [b for b in re.split(r"\n+", text) if b.strip()]:
        ids = re.findall(r"E\d+", block) or all_ids
        clean = DATES.sub(" ", CITE.sub(" ", block))
        m = verify.mechanical({"text": clean, "evidence": ids}, evidence)
        total += m["numbers"]
        untraced += m["untraced"]
    return {"figures": total, "traced": total - len(untraced), "untraced": untraced}


# ---------------------------------------------------------------- threads
def _thread(thread_id: str | None, context: dict, question: str) -> str:
    _init()
    if thread_id and conn().execute("SELECT 1 FROM ask_threads WHERE id=?", (thread_id,)).fetchone():
        conn().execute("UPDATE ask_threads SET updated=?, context=? WHERE id=?", (time.time(), json.dumps(context), thread_id))
        return thread_id
    tid = f"T-{uuid.uuid4().hex[:8]}"
    conn().execute("INSERT INTO ask_threads VALUES(?,?,?,?,?)", (tid, time.time(), time.time(), question[:80], json.dumps(context)))
    return tid


def history(thread_id: str, limit: int = 8) -> list[dict]:
    _init()
    rows = conn().execute("SELECT * FROM ask_messages WHERE thread_id=? ORDER BY ts DESC LIMIT ?", (thread_id, limit)).fetchall()
    return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in reversed(rows)]


def threads(limit: int = 20) -> list[dict]:
    _init()
    return [dict(r) for r in conn().execute("SELECT id, title, updated FROM ask_threads ORDER BY updated DESC LIMIT ?", (limit,))]


def _answer_so_far(buf: str) -> str | None:
    m = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)', buf)
    if not m:
        return None
    raw = m.group(1)
    raw = raw[:-1] if raw.endswith("\\") else raw
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw.replace("\\n", "\n").replace('\\"', '"')


def ask(question: str, thread_id: str | None, context: dict) -> dict:
    tid = _thread(thread_id, context, question)
    past = history(tid, 8)
    now = time.time()
    qid, aid = f"M-{uuid.uuid4().hex[:8]}", f"M-{uuid.uuid4().hex[:8]}"
    conn().execute("INSERT INTO ask_messages VALUES(?,?,?,?,?,?,?)", (qid, tid, now, "user", question, "{}", "done"))
    conn().execute("INSERT INTO ask_messages VALUES(?,?,?,?,?,?,?)", (aid, tid, now + 0.001, "nabd", "", "{}", "running"))

    async def body(progress):
        ev = AskEvidence()
        buf, last = {"s": ""}, {"t": 0.0, "n": 0}

        def relay(kind, data):
            if kind == "text.delta":
                buf["s"] += data.get("delta", "")
                txt = _answer_so_far(buf["s"])
                if txt is not None and time.time() - last["t"] > 0.15:
                    last["t"] = time.time()
                    bus.publish("ask.text", thread_id=tid, message_id=aid, text=txt)
            elif kind == "tool.start":
                last["n"] += 1
                bus.publish("ask.tool", thread_id=tid, message_id=aid, tool=data.get("tool"), args=data.get("args"))

        convo = [{"role": m["role"], "text": (m["content"] or "")[:1500]} for m in past if m["content"]]
        from . import profile
        who = profile.for_prompt()
        prompt = json.dumps({"question": question, "conversation_so_far": convo, "screen": context,
                             "about_the_user": who, "today": time.strftime("%Y-%m-%d")}, indent=1, default=str)
        try:
            res = await gateway.run("ask", RULES, prompt, schema=Answer, tools=tools(ev), on_event=relay,
                                    web_domains=deep.OFFICIAL_DOMAINS, timeout_seconds=300)
            a = res.parsed
            charts = build_charts([c.model_dump() for c in a.charts], ev.items)
            check = figure_check(a.answer, ev.items)
            data = {"charts": charts, "follow_ups": a.follow_ups, "check": check, "model": res.model,
                    "seconds": round(res.ms / 1000, 1),
                    "evidence": {k: {kk: vv for kk, vv in v.items() if kk != "dataset"} for k, v in ev.items.items()}}
            conn().execute("UPDATE ask_messages SET content=?, data=?, status='done' WHERE id=?",
                           (a.answer, json.dumps(data, default=str), aid))
            bus.publish("ask.done", thread_id=tid, message_id=aid)
            return {"thread_id": tid, "tools": last["n"], "figures": check}
        except Exception as exc:
            conn().execute("UPDATE ask_messages SET content=?, status='failed' WHERE id=?",
                           (f"Nabd could not answer: {exc}"[:400], aid))
            bus.publish("ask.done", thread_id=tid, message_id=aid, failed=True)
            raise

    job = runner.start("ask", "Ask Nabd", body, {"thread_id": tid, "message_id": aid})
    return {"thread_id": tid, "question_id": qid, "message_id": aid, "job_id": job}
