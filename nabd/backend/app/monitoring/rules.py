"""Alert rules for data, models, forecasting and fraud (investment rules live in app/invest/monitor.py).

Each rule raises an alert when its condition holds and resolves it when the condition clears. Rules that react to a
change compare with what the previous check saw (kept in the key-value store).
"""

from __future__ import annotations

import time

import numpy as np

from ..core.db import store as kv
from ..data import store
from . import alerts

SOURCE_LABEL = {"markets": "market indicators", "yahoo": "market prices", "fred": "FRED macro series", "gdelt": "news themes",
                "portwatch": "shipping data"}


def data_rules() -> int:
    n = 0
    by_src: dict[str, list[dict]] = {}
    for r in store.catalog():
        by_src.setdefault(r["source"], []).append(r)
    for src, rows in by_src.items():
        bad = [r for r in rows if r["freshness"] in ("late", "error")]
        if bad:
            errors = [r["id"] for r in bad if r["freshness"] == "error"]
            sev = "high" if len(bad) > len(rows) / 2 else "medium"
            what = SOURCE_LABEL.get(src, src)
            n += alerts.raise_alert("data", src, "stale", sev,
                                    f"{len(bad)} of {len(rows)} {what} are {'failing' if errors else 'late'}",
                                    {"series": [r["id"] for r in bad][:20], "errors": errors[:20]})
        else:
            alerts.resolve("data", src, "stale")
    return n


def model_rules() -> int:
    from ..ml.portfolio import ranker, regime
    n = 0
    reg = regime.regime()
    if reg["current"]["stress"] > 0.6:
        n += alerts.raise_alert("models", "regime", "stress", "medium",
                                f"Markets moved into a stress regime ({reg['current']['stress']:.0%} probability)",
                                {"probabilities": reg["current"], "as_of": reg["as_of"]}, link="investment")
    elif reg["current"]["stress"] < 0.4:
        alerts.resolve("models", "regime", "stress")
    rk = ranker.latest() or {}
    hist = [h["ic"] for h in (rk.get("ic_history") or [])[-6:]]
    if len(hist) >= 6 and np.mean(hist) < 0:
        n += alerts.raise_alert("models", "ranker", "drift", "medium",
                                f"Ranking model: average rank IC over the last 6 months is {np.mean(hist):+.3f}",
                                {"ic_last6": hist, "run_id": rk.get("run_id")}, link="investment")
    else:
        alerts.resolve("models", "ranker", "drift")
    last = kv.get("monitor:var") or {}
    if last.get("exceptions_250d", 0) >= 5:  # Basel amber zone or worse (green is 0-4 in 250 days)
        n += alerts.raise_alert("models", "risk", "var_backtest", "high" if last["exceptions_250d"] >= 10 else "medium",
                                f"Risk model VaR backtest: {last['exceptions_250d']} exceptions in 250 days "
                                f"(Basel {'red' if last['exceptions_250d'] >= 10 else 'amber'} zone)", last, link="investment")
    elif last:
        alerts.resolve("models", "risk", "var_backtest")
    return n


def forecasting_rules() -> int:
    from ..ml.forecasting import ai_eval
    out = ai_eval.stored()
    if not out:
        return 0
    n = 0
    seen = kv.get("monitor:nowcast") or {}
    now: dict = {}
    for tname, t in out["targets"].items():
        label = "non-oil GDP" if tname == "non_oil" else "real GDP"
        for q, lq in t["latest"].items():
            v = (lq["models"].get("kalman_ai") or lq["models"].get("kalman") or {}).get("value")
            if v is None:
                continue
            key = f"{tname}:{q}"
            now[key] = v
            prev = seen.get("values", {}).get(key)
            if prev is not None and abs(v - prev) >= 0.75:
                n += alerts.raise_alert("forecasting", key, f"moved:{round(prev, 2)}->{round(v, 2)}", "medium",
                                        f"{q.replace('Q', ' Q')} {label} nowcast moved from {prev:+.1f}% to {v:+.1f}%",
                                        {"from": prev, "to": v, "run_id": out["run_id"]}, link="forecasting")
            if v < 0:
                n += alerts.raise_alert("forecasting", key, "contraction", "medium",
                                        f"Nowcast signals contraction: {q.replace('Q', ' Q')} {label} at {v:+.1f}%",
                                        {"value": v, "bands": (lq["models"].get("kalman_ai") or {}).get("band70")}, link="forecasting")
            else:
                alerts.resolve("forecasting", key, "contraction")
        rel = len(t["released"])
        if seen.get("releases", {}).get(tname) is not None and rel > seen["releases"][tname]:
            last = t["released"][-1]
            n += alerts.raise_alert("forecasting", f"release:{last['quarter']}", "release", "info",
                                    f"FCSC published {last['quarter'].replace('Q', ' Q')} {label}: {last['value']:+.1f}%",
                                    last, link="forecasting")
    kv.set("monitor:nowcast", {"values": now, "ts": time.time(),
                               "releases": {k: len(t["released"]) for k, t in out["targets"].items()}})
    return n


def fraud_rules() -> int:
    from ..ml.fraud import run as fr
    out = fr.latest()
    if not out:
        return 0
    cases = [c for c in out["methods"]["combined"]["cases"] if c["score"] >= 0.9]
    sigs = {",".join(sorted(c["members"])[:3]): c for c in cases}
    seen = set(kv.get("monitor:fraud") or [])
    new = [c for s, c in sigs.items() if s not in seen]
    n = 0
    if new:
        flow = sum(c["flow_aed"] for c in new)
        n += alerts.raise_alert("fraud", out["run_id"], "new_cases", "high",
                                f"{len(new)} new high-risk payment networks, AED {flow / 1e6:.1f} m moved between them",
                                {"cases": [c["id"] for c in new][:30], "run_id": out["run_id"]}, link="fraud")
    kv.set("monitor:fraud", list(set(sigs) | seen))
    return n


def run_once() -> dict:
    out = {}
    for name, fn in (("data", data_rules), ("models", model_rules), ("forecasting", forecasting_rules),
                     ("fraud", fraud_rules)):
        try:
            out[name] = fn()
        except Exception as exc:  # one failing rule must not stop the others
            out[name] = f"error: {type(exc).__name__}: {exc}"[:200]
    kv.set("monitor:last_run", {"ts": time.time(), **{k: v for k, v in out.items()}})
    return out
