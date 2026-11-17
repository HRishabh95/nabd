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
    from ..ml.forecasting import ai_eval
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
    h = ai_eval.headline("non_oil")
    if h:
        out["forecasting"] = {k: h[k] for k in ("pending", "current", "pending_value", "current_value", "last_official",
                                                "run_ts")}
    fd = fraud.latest()
    if fd:
        hi = [c for c in fd["methods"]["combined"]["cases"] if c["score"] >= 0.9]
        out["fraud"] = {"high_risk_cases": len(hi), "flow_aed": sum(c["flow_aed"] for c in hi),
                        "accounts": sum(c["size"] for c in hi), "run_ts": fd["created"],
                        "rules_alerts": (fd.get("benchmarks", {}).get("rules") or fd["methods"].get("rules", {})).get("eval", {}).get("cases"),
                        "precision": fd["methods"]["combined"]["eval"]["precision"]}
    cat = store.catalog()
    out["data"] = {"series": len(cat), "fresh": sum(r["freshness"] == "fresh" for r in cat),
                   "late": sum(r["freshness"] in ("late", "error") for r in cat),
                   "refresh_errors": sum(bool(r.get("refresh_error")) for r in cat),
                   "last_check": (kv.get("monitor:last_run") or {}).get("ts")}
    out["alerts"] = alerts.counts()
    return out


# models that run inside others or are not used by the commodity book: kept in the registry, off the inventory
HIDDEN_MODELS = {"ranker", "regime"}


def basel_zone(exceptions: int) -> str:
    """Basel traffic light for a 99% VaR backtested over 250 days: green 0-4, amber 5-9, red 10 or more."""
    return "green" if exceptions <= 4 else "amber" if exceptions <= 9 else "red"


def _model_status(key: str) -> dict:
    """Live status from the model's own performance against its limits: ok, watch or breach. Known limits of the
    proof of concept (synthetic data, few quarters, the demo LLM provider) are reported as a neutral `note`, not as a
    warning, so a status only turns amber or red when the model itself misbehaves."""
    from ..ml.forecasting import ai_eval
    from ..ml.fraud import run as fraud
    from ..ml.portfolio import ranker, regime
    runs = registry.latest(key, 1)
    last = runs[0] if runs else None
    st, why, metric, note = "ok", "", None, ""
    if key == "risk":
        v = kv.get("monitor:var") or {}
        if v:
            zone = basel_zone(int(v.get("exceptions_250d", 0)))
            metric = f"99% VaR backtest: {v.get('exceptions_250d')} exceptions in 250 days · Basel {zone} zone (green is 0-4)"
            st, why = {"green": ("ok", ""), "amber": ("watch", "Basel amber zone: review the model"),
                       "red": ("breach", "Basel red zone: the model understates risk")}[zone]
        else:
            metric = "VaR backtest not run yet"
    elif key == "regime":
        r = regime.regime()
        metric = f"Now: {r['state']} (stress {r['current']['stress']:.0%}); stress averaged {r['metrics']['stress_in_episodes'].get('COVID crash', 0):.0%} in the COVID crash"
    elif key == "ranker":
        rk = ranker.latest() or {}
        m = rk.get("metrics") or {}
        metric = f"Out-of-sample rank IC {m.get('mean_ic', 0):+.3f} (t {m.get('ic_t_stat', 0)})"
        st, why, note = "inactive", "", "Ranks equities; not used since the investable universe became commodities, gold and bonds"
    elif key == "nowcast":
        h = ai_eval.headline("non_oil")
        sc = {x["model"]: x for x in (h or {}).get("scores", []) if x["horizon"] == "after"}
        if "kalman_ai" in sc and "benchmark" in sc:
            ai, hard = sc["kalman_ai"], sc.get("kalman")
            metric = f"Kalman + AI news: error {ai['rmse']:.2f} pts a month after the quarter, against " \
                     f"{sc['benchmark']['rmse']:.2f} for the last release" + (f" and {hard['rmse']:.2f} without AI" if hard else "")
            if ai["rel_rmse"] and ai["rel_rmse"] >= 1:
                st, why = "breach", "No better than the last release"
        if not h:
            st, why = "watch", "No run yet"
        note = "13 released quarters to learn from, so the bands are wide"
    elif key == "fraud":
        d = fraud.latest()
        if d:
            e = d["methods"]["combined"]["eval"]
            metric = f"Combined: {round(100 * e['precision'])}% precision, {round(100 * e['recall'])}% recall, {e['rings_whole']} of {e['rings']} rings whole"
            if e["precision"] < 0.7:
                st, why = "watch", "Precision below 70%"
        note = "Measured on labelled synthetic payments; to be calibrated on CBUAE data"
    elif key == "stress":
        metric = "Replays, factor shocks and 2,000-path simulation per idea"
    elif key == "thesis":
        rows = conn().execute("SELECT ok FROM llm_calls ORDER BY id DESC LIMIT 50").fetchall()
        if rows:
            okp = sum(r["ok"] for r in rows) / len(rows)
            metric = f"{round(100 * okp)}% of the last {len(rows)} LLM calls succeeded"
            if okp < 0.9:
                st, why = "watch", "LLM call failures above 10%"
        note = "Demo provider (Codex): open and synthetic data only; production uses a model inside CBUAE's boundary"
    return {"status": st, "reason": why, "metric": metric, "note": note,
            "last_run": {"id": last["id"], "created": last["created"]} if last else None}


def explain(key: str) -> dict:
    """What a model does, on what data, how it was tested, what the test found and what it cannot show: in plain
    words, from its latest run, for the inventory's "What this means" panel."""
    from ..data import store
    from ..ml.forecasting import ai_eval
    from ..ml.fraud import run as fraud
    from ..ml.portfolio import reserve
    from ..monitoring import governance
    try:
        last_day = str(store.read_series("yahoo", "GLD")["date"].max().date())
    except Exception:  # noqa: BLE001
        last_day = "the latest close"
    n_lines = len(reserve.SAA)
    if key == "risk":
        v = kv.get("monitor:var") or {}
        return {"short": "The book’s worst likely daily loss, and the risk budget an idea uses",
                "headline": (f"Losses went past the estimate on {v.get('exceptions_250d')} of 250 days (about 2.5 expected)"
                             if v else "Not run yet"),
                "method": "Filtered historical simulation: each past daily return of the book is rescaled to today's "
                          "volatility (RiskMetrics EWMA, lambda 0.94) and the 1st percentile of the rescaled returns is the "
                          "99% value at risk. The risk budget is the idea's tracking error from an EWMA-weighted covariance "
                          "of the book's lines.",
                "what": "Estimates the worst daily loss of the book to expect on 99 days in 100 (value at risk), and how "
                        "much of the Board's risk budget an idea uses against the benchmark.",
                "data": f"Daily prices of the {n_lines} instruments in the book (Yahoo Finance), the last 3 years to {last_day}.",
                "test": "On each of the last 250 trading days, the day's value at risk was set using only the days before "
                        "it, then compared with what the book actually did that day.",
                "result": (f"The loss went past the estimate on {v.get('exceptions_250d')} of 250 days; at 99% about 2.5 "
                           f"are expected. Basel rates 0 to 4 as green. The earlier, plain method was exceeded "
                           f"{v.get('plain_historical_exceptions', '—')} times, which is why it was replaced by filtered "
                           "historical simulation (volatility-adjusted).") if v else "Not run yet.",
                "limit": "Prices are unofficial and delayed; ETFs stand in for the indices and futures a mandate would hold."}
    if key == "stress":
        return {"short": "What an idea would lose in crises and shocks",
                "headline": "Every idea tested on 5 past crises, 4 shocks and 2,000 simulated quarters",
                "method": "Historical replays of five episodes; factor shocks through each line's regression sensitivity to "
                          "Brent, the US 10-year yield, the dollar index and the VIX; Monte Carlo by block bootstrap of real "
                          "63-day stretches of history, 2,000 paths.",
                "what": "Shows what the book and an idea would lose in past crises, under set shocks, and across 2,000 "
                        "simulated quarters.",
                "data": "The same daily prices; five episodes from 2018 to 2025 (Q4 2018 sell-off, Abqaiq attack, COVID "
                        "crash, 2022 rates shock, 2025 tariff shock); sensitivities to oil, rates, the dollar and the VIX.",
                "test": "Replays apply what each holding actually did in the episode; shocks apply each line's measured "
                        "sensitivity; simulations resample real 63-day stretches of history.",
                "result": "Every idea is stress-tested before it reaches the committee; the worst case is shown on the idea.",
                "limit": "The next crisis may not look like a past one; simulations cannot produce moves history never had."}
    if key == "fraud":
        d = fraud.latest() or {}
        e = (d.get("methods") or {}).get("combined", {}).get("eval", {})
        r = (d.get("benchmarks") or {}).get("rules", {}).get("eval", {})
        data = d.get("data", {})
        return {"short": "Finds money-laundering rings in payments",
                "headline": (f"{round(100 * e.get('precision', 0))} in 100 flagged accounts are real launderers; it finds "
                             f"{round(100 * e.get('recall', 0))} in 100 of them" if e else "Not run yet"),
                "method": "Two methods that must agree. (1) A machine-learning risk score for every account: gradient-boosted "
                          "decision trees (scikit-learn HistGradientBoostingClassifier, the XGBoost family) on transfers, "
                          "distinct counterparties, share of money passed straight on, structuring, PageRank on the money "
                          "flows, share of cross-bank transfers and account age. (2) Graph detection that follows the money: "
                          "a transfer is pass-through when the sender received about the same amount shortly before (within "
                          "4 hours, money out 70% to 143% of money in, at least AED 5,000), and linked pass-throughs form a "
                          "group; cycles are money returning to its start in 3 to 7 hops within 3 days. A network is flagged "
                          "when the graph finds it and the ML score is at least 0.25 for its accounts.",
                "methods": [{"label": v["label"], "precision": v["eval"]["precision"], "recall": v["eval"]["recall"],
                             "rings_whole": v["eval"]["rings_whole"], "rings": v["eval"]["rings"],
                             "shown": k in (d.get("methods") or {})}
                            for k, v in {**(d.get("methods") or {}), **(d.get("benchmarks") or {})}.items()],
                "what": "Finds groups of accounts passing money between them the way mule and laundering rings do, and "
                        "scores every account for risk.",
                "data": f"{data.get('transfers', 0):,} synthetic instant payments between {data.get('accounts', 0):,} accounts "
                        f"at {len(data.get('banks', []))} banks over {data.get('days', 0)} days, with {data.get('rings', 0)} "
                        "planted laundering rings whose members are labelled.",
                "test": "Each method's flagged accounts are compared with the labels. The machine-learning score is "
                        "cross-fitted: no ring is scored by a model that saw it in training.",
                "result": (f"{round(100 * e.get('precision', 0))}% of flagged accounts are launderers and "
                           f"{round(100 * e.get('recall', 0))}% of launderers are found; {e.get('rings_whole', 0)} of "
                           f"{e.get('rings', 0)} rings are found whole. Simple per-account rules: "
                           f"{round(100 * r.get('precision', 0))}% precision, no ring found whole.") if e else "Not run yet.",
                "limit": "Synthetic data with labels; on real payments expect lower precision, and tuning with the AML team."}
    if key == "nowcast":
        h = ai_eval.headline("non_oil") or {}
        sc = {x["model"]: x for x in h.get("scores", []) if x["horizon"] == "after"}
        ok = all(k in sc for k in ("kalman_ai", "kalman", "benchmark"))
        return {"short": "UAE GDP before FCSC publishes it",
                "headline": (f"Misses FCSC’s first figure by {sc['kalman_ai']['rmse']:.1f} points with AI news, "
                             f"{sc['kalman']['rmse']:.1f} without, {sc['benchmark']['rmse']:.1f} if we just repeat the last figure"
                             if ok else "Not run yet"),
                "method": "A dynamic factor model with GDP inside it, run through the Kalman filter and smoother, estimated by "
                          "the two-step method of Doz, Giannone and Reichlin (2011). The AI news signal enters as its own "
                          "factor; GDP's weights on the factors are kept at zero or above; each input is capped at three "
                          "standard deviations so one extreme month cannot dominate.",
                "what": "Estimates UAE GDP growth for the quarters FCSC has not yet published, with and without news "
                        "read by AI.",
                "data": "FCSC first releases (13 quarters, 2021 to 2026, with release dates), IMF PortWatch shipping and "
                        "trade volumes, UAE equity prices (Yahoo), and 2,446 UAE business headlines labelled by AI.",
                "test": "For each past quarter the model was refitted using only what had been published by each date, "
                        "at three points in the quarter, and compared with FCSC's first release.",
                "result": (f"Non-oil GDP, a month after the quarter: average error {sc['kalman_ai']['rmse']:.2f} points "
                           f"with AI news, {sc['kalman']['rmse']:.2f} without, {sc['benchmark']['rmse']:.2f} for simply "
                           "repeating the last release.") if ok else "Not run yet.",
                "limit": "Thirteen published quarters with one contraction: differences under about 20% are within noise."}
    if key == "thesis":
        ev = governance.evaluation()
        r = ev["research"]
        return {"short": "Writes theses, research and committee notes",
                "headline": f"{r['traced']} of {r['figures']} figures traced to a source; {r['removed']} of {r['claims']} claims removed",
                "method": "A large language model (Codex, through Nabd's gateway) with structured outputs. Every figure must "
                          "come from a tool (prices, macro series, official documents); a separate step verifies each claim "
                          "against the evidence and removes unsupported ones; a red team argues against the thesis.",
                "what": "Turns a free-text idea into a thesis, proposes what to look at, runs deep research and drafts "
                        "the committee notes.",
                "data": "Only tool results: prices, macro series, official documents and web pages from official domains.",
                "test": "Every figure in research and answers is matched to the tool result it cites; a separate step "
                        "verifies each research claim against the evidence and removes the unsupported ones.",
                "result": f"{r['removed']} of {r['claims']} research claims removed as unsupported; {r['traced']} of "
                          f"{r['figures']} figures traced to evidence.",
                "limit": "The demo provider (Codex) sends prompts outside CBUAE, so only open and synthetic data are used."}
    return {}


@router.get("/models")
def models():
    out = []
    for key, card in registry.MODELS.items():
        if key in HIDDEN_MODELS:
            continue
        out.append({"key": key, **card, **_model_status(key), "explain": explain(key),
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
