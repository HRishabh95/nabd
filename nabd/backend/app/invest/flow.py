"""Stage transitions for an idea. LLM steps run as jobs and stream their progress (tool calls, text) to the UI."""

from __future__ import annotations

import time

import pandas as pd

from ..core.bus import bus
from ..data import store
from ..data.universe import BY_SYMBOL
from ..jobs import runner
from ..ml.portfolio import regime, reserve, risk, stress
from . import agent, ideas, screening


def _relay(idea_id: str, step: str):
    def f(kind, data):
        payload = {k: v for k, v in data.items() if k != "result"}
        if kind == "tool.result":
            payload["ok"] = data.get("ok")
        bus.publish(f"agent.{kind}", idea_id=idea_id, step=step, **payload)
    return f


# ---------- 1. idea → thesis ----------
def start_parse(idea_id: str) -> str:
    async def body(progress):
        idea = ideas.get(idea_id)
        progress(0, 3, "Reading the idea")
        thesis, memory = await agent.parse_thesis(idea, on_event=_relay(idea_id, "thesis"))
        t = thesis.model_dump()
        ideas.update(idea_id, "Nabd", "thesis parsed", stage="screening", thesis=t, title=t["title"],
                     memory_hits=memory)
        ideas.remember(idea_id, "thesis", f"{t['title']}. {t['summary']} Themes: {', '.join(t['themes'])}. "
                                          f"Drivers: {'; '.join(t['drivers'])}")
        progress(2, 3, "Working out what to look at")
        await _propose(ideas.get(idea_id))
        progress(3, 3, "Ready to screen")
        return {"idea_id": idea_id, "title": t["title"]}
    return runner.start("thesis", f"Thesis for {idea_id}", body, {"idea_id": idea_id}, key=f"thesis:{idea_id}")


def edit_thesis(idea_id: str, thesis: dict, actor: str) -> dict:
    return ideas.update(idea_id, actor, "thesis edited", thesis=thesis, title=thesis.get("title"))


async def _propose(idea: dict) -> dict:
    """Codex proposes the driver and the candidates; if it is unavailable, the rule-based screen stands in."""
    import time as _t
    try:
        p = await agent.propose(idea, screening.holdings(), on_event=_relay(idea["id"], "propose"))
        prop = {**p.model_dump(), "source": "llm"}
    except Exception as exc:  # noqa: BLE001 - any LLM failure falls back, and says so on screen
        prop = {**screening.rules_proposal(idea["thesis"] or {}), "source": "rules", "error": f"{type(exc).__name__}"}
    prop["created"] = _t.time()
    ideas.update(idea["id"], "Nabd", "proposed what to look at", proposal=prop)
    return prop


def start_propose(idea_id: str) -> str:
    async def body(progress):
        progress(0, 1, "Working out what to look at")
        prop = await _propose(ideas.get(idea_id))
        progress(1, 1, "Ready")
        return {"idea_id": idea_id, "source": prop["source"], "candidates": len(prop.get("candidates", []))}
    return runner.start("propose", f"What to look at for {idea_id}", body, {"idea_id": idea_id}, key=f"propose:{idea_id}")


def screen(idea_id: str) -> dict:
    """The proposal with evidence, or a running job when Nabd has not proposed yet (ideas made before this step)."""
    idea = ideas.get(idea_id)
    if not idea.get("proposal"):
        return {"status": "proposing", "job_id": start_propose(idea_id)}
    return screening.view(idea["thesis"] or {}, idea["proposal"])


def set_basket(idea_id: str, items: list[dict], funding: str, actor: str) -> dict:
    """Lines to trade (a weight; negative cuts a holding or underweights a name the mandates hold) and lines to
    research only (no weight: deep research studies them, the risk model ignores them)."""
    lines = [{"symbol": i["symbol"], "weight_pct": 0.0 if i.get("research_only") else float(i["weight_pct"]),
              "research_only": bool(i.get("research_only")),
              "name": BY_SYMBOL[i["symbol"]].name if i["symbol"] in BY_SYMBOL else i["symbol"]} for i in items]
    basket = {"items": lines, "total_pct": round(sum(b["weight_pct"] for b in lines), 3)}
    return ideas.update(idea_id, actor, "basket selected", stage="research", basket=basket, funding=funding)


def preview(idea: dict, items: list[dict], funding: str) -> dict:
    """The portfolio before and after a selection: by asset class, the lines it touches, the exposure to the idea's
    driver and the risk budget used. Computed, not saved; shown before research starts so the team can check the
    selection does what the idea says."""
    from ..data.universe import BY_SYMBOL as U
    tilt = trade_lines({"items": [{**i, "weight_pct": 0.0 if i.get("research_only") else float(i.get("weight_pct") or 0)}
                                   for i in items]})
    existing = ideas.active_positions()
    base = dict(reserve.benchmark_weights())
    for s_, w in existing.items():
        base[s_] = base.get(s_, 0.0) + w
    active = risk.active_from_tilt(tilt, funding) if tilt else {}
    after = dict(base)
    for s_, w in active.items():
        after[s_] = after.get(s_, 0.0) + w

    def group(s_: str) -> str:
        inst = U.get(s_)
        if not inst:
            return "Other"
        if "cash" in inst.tags:
            return "Cash and T-bills"
        return {"equity": "Equities", "bond": "Bonds", "gold": "Gold"}.get(inst.asset, "Other")
    groups: dict[str, list[float]] = {}
    for s_ in set(base) | set(after):
        g = groups.setdefault(group(s_), [0.0, 0.0])
        g[0] += base.get(s_, 0.0) * 100
        g[1] += after.get(s_, 0.0) * 100
    order = ["Equities", "Bonds", "Cash and T-bills", "Gold", "Other"]
    by_class = [{"name": k, "before_pct": round(groups[k][0], 2), "after_pct": round(groups[k][1], 2)} for k in order if k in groups]
    lines = [{"symbol": s_, "name": U[s_].name if s_ in U else s_, "before_pct": round(base.get(s_, 0.0) * 100, 3),
              "after_pct": round(after.get(s_, 0.0) * 100, 3)} for s_ in sorted(active, key=lambda x: -abs(active[x]))
             if abs(active[s_]) > 1e-9]
    # exposure to the driver Nabd identified for this idea, before and after
    prop = screening.clean_proposal(idea.get("proposal") or {}) if idea.get("proposal") else None
    driver = None
    if prop and prop["driver_symbols"]:
        syms = set(prop["driver_symbols"]) | set(base) | set(after)
        R = screening._returns(list(syms)).fillna(0.0)
        d = R[[x for x in prop["driver_symbols"] if x in R]].mean(axis=1)
        betas = {x: float(R[x].cov(d) / d.var()) for x in syms if x in R and d.var() > 0}
        # equity lines only, the same measure as the screen's 'moves like' figure, so the two numbers agree
        exp = lambda w: round(sum(v * 100 * betas.get(k, 0.0) for k, v in w.items() if k in U and U[k].asset == "equity"), 2)  # noqa: E731
        driver = {"label": prop.get("driver_label"), "before_pct": exp(base), "after_pct": exp(after)}
    r = risk.analyse(active, existing, subject=idea["id"]) if active else None
    warnings = []
    bearish = (idea.get("thesis") or {}).get("direction") == "underweight"
    if not tilt:
        warnings.append("Nothing is traded: every name is research only, so portfolio fit and stress will have nothing to test.")
    elif driver and bearish and driver["after_pct"] >= driver["before_pct"] - 0.05:
        warnings.append(f"This selection does not reduce your exposure to {driver['label']}. To act on the idea, cut a "
                        "holding that moves with it, or size the protection to offset it.")
    elif driver and not bearish and driver["after_pct"] <= driver["before_pct"] + 0.05:
        warnings.append(f"This selection does not add exposure to {driver['label']}.")
    return {
        "trades": [{"symbol": k, "name": U[k].name if k in U else k, "weight_pct": v} for k, v in tilt.items()],
        "research_only": [{"symbol": i["symbol"], "name": U[i["symbol"]].name} for i in items if i.get("research_only")],
        "funding": funding, "by_class": by_class, "lines": lines, "driver": driver,
        "risk": {"te_bp_after": r["te_bp"]["after"], "budget_used_before_pct": r["budget_used_pct"]["before"],
                 "budget_used_after_pct": r["budget_used_pct"]["after"], "budget_bp": r["budget_bp"]} if r else None,
        "warnings": warnings,
    }


def adopt_split(idea_id: str, items: list[dict], actor: str) -> dict:
    """Make research's proposed split the selection without re-running research, and recompute portfolio fit."""
    idea = ideas.get(idea_id)
    lines = [{"symbol": i["symbol"], "weight_pct": 0.0 if i.get("research_only") else float(i["weight_pct"]),
              "research_only": bool(i.get("research_only")), "name": BY_SYMBOL[i["symbol"]].name} for i in items]
    basket = {"items": lines, "total_pct": round(sum(b["weight_pct"] for b in lines), 3)}
    stage = "fit" if idea["stage"] in ("research", "fit", "stress", "committee") else idea["stage"]
    # stress and the committee pack described the old selection: clear them so they are run again on this one
    ideas.update(idea_id, actor, "adopted the split proposed by research", basket=basket, stage=stage, stress=None, committee=None)
    return {"fit": compute_fit(idea_id, actor)}


# ---------- 2. research ----------
def start_research(idea_id: str, as_of: str | None = None, web: bool = True) -> str:
    """Research is the deep pipeline (plan, parallel workers, red team, verification, synthesis)."""
    from . import deep
    return deep.start(idea_id, as_of, web)


def start_quick_research(idea_id: str) -> str:
    async def body(progress):
        idea = ideas.get(idea_id)
        progress(0, 1, "Researching")
        out = await agent.write_research(idea, on_event=_relay(idea_id, "research"))
        ideas.update(idea_id, "Nabd", "research written", stage="fit", research=out)
        ideas.remember(idea_id, "research", out["note"]["summary"])
        progress(1, 1, "Research ready")
        return {"idea_id": idea_id, "evidence": len(out["evidence"])}
    return runner.start("research", f"Research for {idea_id}", body, {"idea_id": idea_id}, key=f"research:{idea_id}")


# ---------- 3. portfolio fit ----------
def _tilt(idea: dict) -> dict[str, float]:
    """The traded lines only: research-only names carry no weight."""
    return trade_lines(idea["basket"])


def trade_lines(basket: dict | None) -> dict[str, float]:
    return {b["symbol"]: b["weight_pct"] for b in (basket or {}).get("items", [])
            if not b.get("research_only") and b["weight_pct"]}


def compute_fit(idea_id: str, actor: str = "Nabd") -> dict:
    idea = ideas.get(idea_id)
    tilt = _tilt(idea)
    existing = {s: w for s, w in ideas.active_positions().items()}
    active = risk.active_from_tilt(tilt, idea.get("funding") or "equity")
    r = risk.analyse(active, existing, subject=idea_id)
    mult = risk.max_size_within_budget(tilt, existing, idea.get("funding") or "equity")
    notional = reserve.NOTIONAL_USD_BN
    liquidity = []
    for s, w in tilt.items():
        try:
            st = risk.price_stats(s)
        except FileNotFoundError:
            continue
        pos_usd_mn = w / 100 * notional * 1e3
        adv = st["avg_daily_value_traded_usd_mn"] or 0
        liquidity.append({"symbol": s, "position_usd_mn": round(pos_usd_mn, 1), "adv_usd_mn": adv,
                          "days_at_20pct_adv": round(pos_usd_mn / (0.2 * adv), 1) if adv else None})
    # SRI screening applies to equity indices; gold, bonds and cash are outside it
    sri = [s for s in tilt if s in BY_SYMBOL and BY_SYMBOL[s].asset == "equity" and not BY_SYMBOL[s].sri]
    fit = {**r, "tilt": tilt, "active": {k: round(v * 100, 3) for k, v in active.items()},
           "max_multiple": round(mult, 2), "max_total_pct": round(sum(tilt.values()) * mult, 2),
           "liquidity": liquidity, "non_sri_lines": sri, "funding": idea.get("funding") or "equity",
           "regime": regime.regime()["current"]}
    ideas.update(idea_id, actor, "fit computed", stage="stress" if idea["stage"] in ("fit", "research") else None,
                 fit=fit)
    return fit


def resize(idea_id: str, multiple: float, actor: str) -> dict:
    idea = ideas.get(idea_id)
    from . import lookthrough
    from .screening import holdings
    held = {h["symbol"]: h["weight_pct"] for h in holdings()}
    via = lookthrough.indirect(held)

    def scaled(b: dict) -> float:  # a cut never grows past what is held (directly or through the mandates)
        w = b["weight_pct"] * multiple
        return round(max(w, -(held.get(b["symbol"], 0.0) + via.get(b["symbol"], 0.0))) if w < 0 else w, 3)
    items = [{**b, "weight_pct": scaled(b)} for b in idea["basket"]["items"]]
    basket = {**idea["basket"], "items": items, "total_pct": round(sum(i["weight_pct"] for i in items), 3)}
    ideas.update(idea_id, actor, f"resized ×{multiple:.2f}", basket=basket)
    return compute_fit(idea_id, actor)


# ---------- 4. stress ----------
def start_stress(idea_id: str) -> str:
    async def body(progress):
        import asyncio
        idea = ideas.get(idea_id)
        progress(0, 1, "Running replays, shocks and 2,000 simulations")
        active = risk.active_from_tilt(_tilt(idea), idea.get("funding") or "equity")
        existing = ideas.active_positions() if idea["stage"] != "position" else {}
        out = await asyncio.to_thread(stress.run, active, idea_id, 7, existing)
        ideas.update(idea_id, "Nabd", "stress run", stage="committee", stress=out)
        progress(1, 1, "Stress ready")
        return {"idea_id": idea_id, "worst": out["worst"]}
    return runner.start("stress", f"Stress for {idea_id}", body, {"idea_id": idea_id}, key=f"stress:{idea_id}")


# ---------- 5. committee ----------
def build_pack(idea: dict) -> dict:
    fit, st, r = idea.get("fit") or {}, idea.get("stress") or {}, idea.get("research") or {}
    if r.get("kind") == "deep" and r.get("synthesis"):
        syn = r["synthesis"]
        note = {"summary": f"{syn['headline']} {syn['summary']}",
                "risks": [{"text": p["text"]} for p in (r.get("red_team") or {}).get("points", [])]}
        research_extra = {"overall": syn["overall"], "confidence": syn["confidence"],
                          "hypotheses": syn["hypotheses"], "bear_case": (r.get("red_team") or {}).get("bear_case"),
                          "verification": (r.get("verification") or {}).get("stats")}
    else:
        note, research_extra = r.get("note") or {}, None
    return {
        "idea": {"id": idea["id"], "title": idea["title"], "horizon": idea["horizon"], "owner": idea["owner"]},
        "thesis": idea["thesis"], "basket": idea["basket"], "funding": idea.get("funding"),
        "research_summary": note.get("summary"), "risks_from_research": [p["text"] for p in note.get("risks", [])],
        "deep_research": research_extra,
        "portfolio_fit": {k: fit.get(k) for k in ("te_bp", "budget_bp", "budget_used_pct", "corr_with_existing",
                                                  "active_var95_usd_mn", "max_total_pct", "liquidity",
                                                  "non_sri_lines", "run_id")},
        "stress": {"worst": st.get("worst"), "replays": [{k: r[k] for k in ("name", "active_bp", "active_usd_mn")}
                                                         for r in st.get("replays", [])],
                   "shocks": [{k: r[k] for k in ("name", "active_bp", "active_usd_mn")} for r in st.get("shocks", [])],
                   "monte_carlo": {k: (st.get("monte_carlo") or {}).get(k) for k in
                                   ("active_bp_percentiles", "prob_active_loss", "active_es95_bp")},
                   "run_id": st.get("run_id")},
        "proposed_exit": idea.get("exit_plan"),
        "notional_usd_bn": reserve.NOTIONAL_USD_BN,
    }


def default_exit_plan(idea: dict) -> dict:
    days = 126 if idea["horizon"] == "tactical" else 756
    triggers = [t for t in (idea["thesis"] or {}).get("invalidation", []) if t.get("series") and t.get("op")]
    syn = (idea.get("research") or {}).get("synthesis") or {}
    known = {t["series"] for t in triggers}
    for t in syn.get("proposed_triggers", []):  # triggers proposed by deep research, if Nabd can watch them
        if t.get("series") and t.get("op") and t.get("value") is not None and t["series"] not in known \
                and (t["series"] == "regime:stress" or store.source_of(t["series"])):
            triggers.append(t)
            known.add(t["series"])
    return {"target_active_bp": 40 if idea["horizon"] == "tactical" else 150,
            "stop_active_bp": -25 if idea["horizon"] == "tactical" else -75,
            "review_by": time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 1.45 * 86400)),
            "invalidation": triggers, "rebalance": "Unwind to benchmark weights over 5 trading days"}


def start_committee(idea_id: str) -> str:
    async def body(progress):
        idea = ideas.get(idea_id)
        if not idea.get("exit_plan"):
            idea = ideas.update(idea_id, "Nabd", "exit plan proposed", exit_plan=default_exit_plan(idea))
        pack = build_pack(idea)
        progress(0, 1, "Drafting the cover note")
        cover = await agent.write_cover_note(idea, pack, on_event=_relay(idea_id, "committee"))
        committee = {"pack": pack, "cover": cover.model_dump(), "prepared": time.time(),
                     "risk_signoff": None, "decision": None}
        ideas.update(idea_id, "Nabd", "committee pack prepared", committee=committee)
        progress(1, 1, "Pack ready")
        return {"idea_id": idea_id}
    return runner.start("committee", f"Committee pack for {idea_id}", body, {"idea_id": idea_id},
                        key=f"committee:{idea_id}")


def set_exit_plan(idea_id: str, plan: dict, actor: str) -> dict:
    return ideas.update(idea_id, actor, "exit plan set", exit_plan=plan)


def risk_signoff(idea_id: str, opinion: str, comment: str, actor: str) -> dict:
    idea = ideas.get(idea_id)
    c = idea["committee"]
    c["risk_signoff"] = {"opinion": opinion, "comment": comment, "by": actor, "ts": time.time()}
    return ideas.update(idea_id, actor, f"risk sign-off: {opinion}", committee=c)


def decide(idea_id: str, decision: str, conditions: str, rationale: str, actor: str) -> dict:
    idea = ideas.get(idea_id)
    c = idea["committee"]
    if not c.get("risk_signoff"):
        raise ValueError("Risk sign-off is required before the committee decides")
    c["decision"] = {"decision": decision, "conditions": conditions, "rationale": rationale, "by": actor,
                     "ts": time.time()}
    ideas.remember(idea_id, "decision", f"{c['pack']['idea']['title']}: {decision}. {rationale} {conditions}")
    if decision == "approve":
        entry = {s: _last_price(s) for s in [b["symbol"] for b in idea["basket"]["items"]] +
                 list(reserve.equity_sleeve()) + ["SHV"]}
        position = {"opened": time.time(), "entry_date": time.strftime("%Y-%m-%d"), "entry_prices": entry,
                    "health": None, "history": []}
        return ideas.update(idea_id, actor, "approved", stage="position", committee=c, position=position)
    if decision == "reject":
        return ideas.update(idea_id, actor, "rejected", stage="closed", status="rejected", committee=c)
    return ideas.update(idea_id, actor, "deferred", committee=c)


def _last_price(symbol: str) -> float | None:
    try:
        return float(store.read_series("yahoo", symbol)["adjclose"].dropna().iloc[-1])
    except (FileNotFoundError, IndexError):
        return None


def close(idea_id: str, reason: str, actor: str) -> str:
    async def body(progress):
        idea = ideas.get(idea_id)
        outcome = {"reason": reason, "health": (idea.get("position") or {}).get("health")}
        lesson = await agent.write_lesson(idea, outcome)
        pos = idea.get("position") or {}
        pos["closed"] = {"ts": time.time(), "reason": reason, "lesson": lesson.model_dump()}
        ideas.update(idea_id, actor, "closed", stage="closed", status="closed", position=pos)
        ideas.remember(idea_id, "lesson", f"{idea['title']}: {lesson.outcome} Lesson: {lesson.lesson}")
        return {"idea_id": idea_id}
    return runner.start("close", f"Close {idea_id}", body, {"idea_id": idea_id}, key=f"close:{idea_id}")


def series_value(series: str) -> tuple[float | None, str | None]:
    """Latest value of a watchable series id (FRED id, news:<theme>, regime:stress, or a symbol)."""
    if series == "regime:stress":
        r = regime.regime()
        return r["current"]["stress"], r["as_of"]
    src = store.source_of(series)
    if not src:
        return None, None
    df = store.read_series(src, series)
    col = "adjclose" if "adjclose" in df else ("volume" if src == "gdelt" else "value")
    s = df.dropna(subset=[col])
    return (float(s[col].iloc[-1]), str(pd.Timestamp(s["date"].iloc[-1]).date())) if len(s) else (None, None)
