"""Monitoring API: the alert inbox, today's summary per module, the model registry, and the audit log."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter

from ..core.db import conn
from ..core.db import store as kv
from ..data import store
from ..ml import registry
from ..monitoring import alerts

router = APIRouter(prefix="/api/monitor")
USER = "Investment team"


@router.get("/alerts")
def list_alerts(status: str = "active", module: str | None = None):
    return {"alerts": alerts.listing(status, module), "counts": alerts.counts()}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int):
    alerts.ack(alert_id, USER)
    return {"ok": True}


@router.post("/check")
async def check():
    import asyncio

    from ..invest import monitor
    from ..monitoring import rules
    await asyncio.to_thread(monitor.run_once)
    return await asyncio.to_thread(rules.run_once)


@router.get("/summary")
def summary():
    from ..invest import ideas
    from ..ml.forecasting import run as fr
    from ..ml.fraud import run as fraud
    from ..ml.portfolio import regime, reserve, risk

    out: dict = {"ts": time.time()}
    pos = [i for i in ideas.all_ideas() if i["stage"] == "position"]
    r = risk.analyse({}, ideas.active_positions(), subject="overview")
    health = [((i.get("position") or {}).get("health") or {}).get("score") for i in pos]
    out["investment"] = {"budget_used_pct": r["budget_used_pct"]["before"], "budget_bp": reserve.ACTIVE_RISK_BUDGET_BP,
                         "monitored": len(pos), "health_min": min([h for h in health if h is not None], default=None),
                         "in_progress": sum(i["stage"] not in ("position", "closed") for i in ideas.all_ideas()),
                         "regime": regime.regime()["state"]}
    f = fr.latest()
    if f:
        t = f["targets"]["non_oil"]
        out["forecasting"] = {"pending": t["pending"], "current": t["current"],
                              "pending_value": (t["latest"].get(t["pending"], {}).get("models", {}).get("ensemble") or {}).get("value"),
                              "current_value": (t["latest"].get(t["current"], {}).get("models", {}).get("ensemble") or {}).get("value"),
                              "last_official": t["released"][-1] if t["released"] else None,
                              "champion": (t.get("champion") or {}).get("model"), "run_ts": f["created"]}
    fd = fraud.latest()
    if fd:
        hi = [c for c in fd["methods"]["combined"]["cases"] if c["score"] >= 0.9]
        out["fraud"] = {"high_risk_cases": len(hi), "flow_aed": sum(c["flow_aed"] for c in hi),
                        "accounts": sum(c["size"] for c in hi), "run_ts": fd["created"],
                        "rules_alerts": fd["methods"]["rules"]["eval"]["cases"],
                        "precision": fd["methods"]["combined"]["eval"]["precision"]}
    cat = store.catalog()
    out["data"] = {"series": len(cat), "fresh": sum(r["freshness"] == "fresh" for r in cat),
                   "late": sum(r["freshness"] in ("late", "error") for r in cat),
                   "refresh_errors": sum(bool(r.get("refresh_error")) for r in cat),
                   "last_check": (kv.get("monitor:last_run") or {}).get("ts")}
    out["alerts"] = alerts.counts()
    return out


def _model_status(key: str) -> dict:
    """Live status of a model from its latest run: ok, watch or breach, with the reason in plain words."""
    from ..ml.forecasting import run as fr
    from ..ml.fraud import run as fraud
    from ..ml.portfolio import ranker, regime
    runs = registry.latest(key, 1)
    last = runs[0] if runs else None
    st, why, metric = "ok", "", None
    if key == "risk":
        v = kv.get("monitor:var") or {}
        metric = f"VaR backtest: {v.get('exceptions_250d', '—')} exceptions in 250 days (limit {v.get('limit', 4)})"
        if v and v.get("exceptions_250d", 0) > v.get("limit", 4):
            st, why = "breach", "Backtest exceptions above the limit"
        elif v and v.get("exceptions_250d", 0) == v.get("limit", 4):
            st, why = "watch", "Backtest exceptions at the limit"
    elif key == "regime":
        r = regime.regime()
        metric = f"Now: {r['state']} (stress {r['current']['stress']:.0%}); stress averaged {r['metrics']['stress_in_episodes'].get('COVID crash', 0):.0%} in the COVID crash"
    elif key == "ranker":
        rk = ranker.latest() or {}
        m = rk.get("metrics") or {}
        metric = f"Out-of-sample rank IC {m.get('mean_ic', 0):+.3f} (t {m.get('ic_t_stat', 0)}), right in {round(100 * m.get('hit_rate', 0))}% of months"
        if m and m.get("ic_t_stat", 0) < 2:
            st, why = "watch", "Signal is weak (t below 2); used as one input only"
    elif key == "nowcast":
        f = fr.latest()
        c = (f or {}).get("targets", {}).get("non_oil", {}).get("champion") if f else None
        if c:
            metric = f"Champion {c['model']}: error {c['rmse']:.2f} pts, {round(100 * (1 - c['rel_rmse']))}% below the benchmark"
            if c["rel_rmse"] >= 1:
                st, why = "breach", "Champion no better than the benchmark"
        st, why = (st, why) if f else ("watch", "No run yet")
        if f:
            st, why = (("watch", "About 16 target quarters; wide bands") if st == "ok" else (st, why))
    elif key == "fraud":
        d = fraud.latest()
        if d:
            e = d["methods"]["combined"]["eval"]
            metric = f"Combined: {round(100 * e['precision'])}% precision, {round(100 * e['recall'])}% recall, {e['rings_whole']} of {e['rings']} rings whole"
            st, why = "watch", "Scored on synthetic data; calibrate on CBUAE payments"
    elif key == "stress":
        metric = "Replays, factor shocks and 2,000-path simulation per idea"
    elif key == "thesis":
        rows = conn().execute("SELECT ok FROM llm_calls ORDER BY id DESC LIMIT 50").fetchall()
        if rows:
            okp = sum(r["ok"] for r in rows) / len(rows)
            metric = f"{round(100 * okp)}% of the last {len(rows)} LLM calls succeeded"
            if okp < 0.9:
                st, why = "watch", "LLM call failures above 10%"
        st, why = (st, why) if st != "ok" else ("watch", "Codex demo provider: open data only")
    return {"status": st, "reason": why, "metric": metric,
            "last_run": {"id": last["id"], "created": last["created"]} if last else None}


@router.get("/models")
def models():
    out = []
    for key, card in registry.MODELS.items():
        out.append({"key": key, **card, **_model_status(key),
                    "lifecycle": "Development (POC): independent validation not yet performed",
                    "recent_runs": [{"id": r["id"], "created": r["created"]} for r in registry.latest(key, 5)]})
    return {"models": out}


@router.get("/audit")
def audit(limit: int = 60):
    from ..invest import ideas
    from ..jobs import runner
    ideas._init(), runner._init(), alerts._init()  # a fresh install may not have created these tables yet
    events = []
    for r in conn().execute("SELECT ts, actor, stage, action, idea_id FROM idea_events ORDER BY ts DESC LIMIT ?", (limit,)):
        events.append({"ts": r["ts"], "module": "investment", "actor": r["actor"], "action": r["action"],
                       "subject": r["idea_id"], "link": f"investment/{r['idea_id']}"})
    for r in conn().execute("SELECT started, finished, kind, label, status, id FROM jobs ORDER BY started DESC LIMIT ?", (limit,)):
        events.append({"ts": r["finished"] or r["started"], "module": "jobs", "actor": "Nabd",
                       "action": f"{r['label']}: {r['status']}", "subject": r["id"], "link": None})
    for r in conn().execute("SELECT ts, acked_ts, acked_by, title, module, status FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)):
        events.append({"ts": r["ts"], "module": r["module"], "actor": "Nabd monitor", "action": f"Alert: {r['title']}",
                       "subject": None, "link": None})
        if r["acked_ts"]:
            events.append({"ts": r["acked_ts"], "module": r["module"], "actor": r["acked_by"],
                           "action": f"Acknowledged: {r['title']}", "subject": None, "link": None})
    for r in conn().execute("SELECT ts, actor, action, subject, detail FROM audit ORDER BY ts DESC LIMIT ?", (limit,)):
        events.append({"ts": r["ts"], "module": "system", "actor": r["actor"], "action": r["action"],
                       "subject": r["subject"], "link": None, "detail": json.loads(r["detail"] or "{}")})
    events.sort(key=lambda e: -(e["ts"] or 0))
    return {"events": events[:limit]}
