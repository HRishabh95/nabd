"""Continuous monitoring of approved ideas, and the alert store.

After each data refresh (and every 15 minutes) every monitored idea is re-checked:
- active return since entry (the tilt against its funding, from entry prices), against target and stop;
- days to the review date;
- each invalidation trigger on its latest value;
- tone of the news themes in the thesis over the last 3 days against the prior 4 weeks;
- the regime's stress probability, and the portfolio's share of the active risk budget.
These roll up into a thesis-health score (0-100). A breach raises an alert once (deduplicated while open), streams
it to every open page, and records it on the idea's audit trail.
"""

from __future__ import annotations

import asyncio
import json
import time

from ..core.bus import bus
from ..core.db import conn  # noqa: F401  (used by run_once)
from ..data import store
from ..ml.portfolio import regime, reserve, risk
from ..monitoring import alerts as store_alerts
from . import flow, ideas


def raise_alert(idea_id: str | None, rule: str, severity: str, title: str, detail: dict) -> bool:
    """Investment alerts go to the shared store; an idea's alert links to the idea and is logged on its trail."""
    opened = store_alerts.raise_alert("investment", idea_id or "portfolio", rule, severity, title, detail,
                                      link=f"investment/{idea_id}" if idea_id else "investment", idea_id=idea_id)
    if opened and idea_id:
        ideas.log(idea_id, "Nabd monitor", "position", "alert", {"rule": rule, "title": title})
    return opened


def resolve(idea_id: str | None, rule: str) -> None:
    store_alerts.resolve("investment", idea_id or "portfolio", rule)


def alerts(status: str | None = None, limit: int = 50) -> list[dict]:
    return store_alerts.listing(status, "investment", limit)


def ack(alert_id: int, actor: str) -> None:
    store_alerts.ack(alert_id, actor)


def _active_return_bp(idea: dict) -> float | None:
    pos = idea["position"]
    entry = pos.get("entry_prices") or {}
    active = risk.active_from_tilt({b["symbol"]: b["weight_pct"] for b in idea["basket"]["items"]
                                    if not b.get("research_only") and b["weight_pct"]},
                                   idea.get("funding") or "equity")
    total = 0.0
    for s, w in active.items():
        p0, p1 = entry.get(s), flow._last_price(s)
        if not p0 or not p1:
            return None
        total += w * (p1 / p0 - 1)
    return round(total * 1e4, 1)


def check_idea(idea: dict) -> dict:
    plan = idea.get("exit_plan") or {}
    checks, score = [], 100.0
    ar = _active_return_bp(idea)
    if ar is not None:
        tgt, stop = plan.get("target_active_bp"), plan.get("stop_active_bp")
        status = "ok"
        if stop is not None and ar <= stop:
            status, score = "breach", score - 45
            raise_alert(idea["id"], "stop", "high", f"{idea['title']}: stop reached",
                        {"active_bp": ar, "stop_bp": stop})
        elif tgt is not None and ar >= tgt:
            status = "target"
            raise_alert(idea["id"], "target", "info", f"{idea['title']}: target reached, review exit",
                        {"active_bp": ar, "target_bp": tgt})
        elif stop is not None and ar <= stop / 2:
            status, score = "watch", score - 15
        checks.append({"name": "Active return since entry", "value": f"{ar:+.1f} bp",
                       "limit": f"target {tgt:+} bp, stop {stop:+} bp", "status": status})
    review = plan.get("review_by")
    if review:
        days = (time.mktime(time.strptime(review, "%Y-%m-%d")) - time.time()) / 86400
        st = "breach" if days < 0 else ("watch" if days < 14 else "ok")
        if days < 0:
            score -= 10
            raise_alert(idea["id"], "time", "medium", f"{idea['title']}: review date passed", {"review_by": review})
        checks.append({"name": "Review date", "value": review, "limit": f"{days:.0f} days left", "status": st})
    for i, t in enumerate(plan.get("invalidation") or []):
        val, asof = flow.series_value(t["series"])
        if val is None:
            checks.append({"name": t["label"], "value": "no data", "limit": t["series"], "status": "unknown"})
            continue
        hit = (val > t["value"]) if t["op"] == ">" else (val < t["value"])
        if hit:
            score -= 25
            raise_alert(idea["id"], f"invalidation:{i}", "high", f"{idea['title']}: {t['label']}",
                        {"series": t["series"], "value": val, "threshold": t["value"], "op": t["op"], "as_of": asof})
        else:
            resolve(idea["id"], f"invalidation:{i}")
        checks.append({"name": t["label"], "value": f"{val:.3g} ({asof})", "limit": f"{t['op']} {t['value']}",
                       "status": "breach" if hit else "ok", "series": t["series"]})
    for th in (idea.get("thesis") or {}).get("themes", []):
        sid = f"news:{th}"
        if not store.source_of(sid):
            continue
        df = store.read_series("gdelt", sid).tail(31)
        if len(df) < 10:
            continue
        recent, prior = float(df.tone.tail(3).mean()), float(df.tone.head(28).mean())
        drop = recent - prior
        st = "watch" if drop < -1.0 else "ok"
        if drop < -1.5:
            score -= 10
            raise_alert(idea["id"], f"news:{th}", "medium", f"{idea['title']}: news tone on {th} fell sharply",
                        {"recent_tone": round(recent, 2), "prior_tone": round(prior, 2)})
        checks.append({"name": f"News tone: {th}", "value": f"{recent:+.2f}", "limit": f"4-week {prior:+.2f}",
                       "status": st, "series": sid})
    stress_p = regime.regime()["current"]["stress"]
    if stress_p > 0.6:
        score -= 10
    checks.append({"name": "Market stress probability", "value": f"{stress_p:.0%}", "limit": "watch above 60%",
                   "status": "watch" if stress_p > 0.6 else "ok", "series": "regime:stress"})
    health = {"score": max(0, round(score)), "checks": checks, "active_bp": ar, "ts": time.time()}
    return health


def run_once() -> dict:
    checked = 0
    for idea in ideas.all_ideas():
        if idea["stage"] != "position":
            continue
        health = check_idea(idea)
        pos = idea["position"]
        hist = (pos.get("history") or [])[-500:]
        hist.append({"ts": health["ts"], "score": health["score"], "active_bp": health["active_bp"]})
        pos.update(health=health, history=hist)
        conn().execute("UPDATE ideas SET position=?, updated=? WHERE id=?",
                       (json.dumps(pos, default=str), time.time(), idea["id"]))
        bus.publish("idea.health", idea_id=idea["id"], score=health["score"], active_bp=health["active_bp"])
        checked += 1
    # portfolio-level rule: share of the active risk budget in use
    existing = ideas.active_positions()
    from ..core.db import store as kv
    r_all = risk.analyse({}, existing, subject="portfolio")
    kv.set("monitor:var", {**r_all["var_backtest"], "run_id": r_all["run_id"], "ts": time.time()})
    if existing:
        r = r_all
        used = r["budget_used_pct"]["before"]
        if used > 90:
            raise_alert(None, "budget", "high", f"Active risk budget {used:.0f}% used",
                        {"te_bp": r["te_bp"]["before"], "budget_bp": reserve.ACTIVE_RISK_BUDGET_BP})
        else:
            resolve(None, "budget")
    return {"checked": checked}


async def monitor_loop():
    """Re-check ideas and every module's rules after data refreshes, idea changes and model runs (and every 15
    minutes regardless)."""
    from ..monitoring import rules

    q = bus.subscribe()
    last = 0.0
    while True:
        try:
            event = await asyncio.wait_for(q.get(), 900)
            relevant = event.type in ("data.refreshed", "idea.updated") or (
                event.type == "job.done" and event.data.get("kind") in ("nowcast", "fraud", "ranker"))
            if not relevant or time.time() - last < 20:
                continue
        except TimeoutError:
            pass
        last = time.time()
        for fn in (run_once, rules.run_once):
            try:
                await asyncio.to_thread(fn)
            except Exception as exc:  # monitoring must never stop the app
                bus.publish("monitor.error", error=str(exc)[:200])
