"""Forecasting run: pseudo real-time backtest, weekly nowcast paths, champion selection, contributions, scenarios.

Pseudo real-time: every nowcast uses only target values released by its date (first releases, with release dates)
and indicator data inside their publication lags. Market and shipping data are not revised, so their final values
stand in for vintages; GDP is scored against FIRST releases.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ...core.db import store as kv
from .. import registry
from . import data, models

HORIZONS = {"mid": 45, "end": 91, "after": 121}  # days after the quarter starts: mid-quarter, at its end, a month later
HORIZON_LABEL = {"mid": "Mid-quarter", "end": "Quarter end", "after": "One month after"}
Z70, Z90 = 1.036, 1.645


def _q_start(q: pd.Period) -> pd.Timestamp:
    return q.asfreq("D", "start").to_timestamp()


def backtest(target: str, progress=None, start_step: int = 0, total: int = 1) -> dict:
    rec = data.target_record()
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    evalq = rec.dropna(subset=[col, "release_date"])
    rows, step = [], start_step
    for _, r in evalq.iterrows():
        q = r["period"]
        for h, days in HORIZONS.items():
            as_of = min(_q_start(q) + pd.Timedelta(days=days), r["release_date"] - pd.Timedelta(days=1))
            out = models.nowcast(target, q, as_of)
            for m, v in out["models"].items():
                rows.append({"quarter": str(q), "horizon": h, "as_of": str(as_of.date()), "model": m,
                             "nowcast": round(v["value"], 3), "actual": float(r[col]),
                             "error": round(v["value"] - float(r[col]), 3), "train": out["train_quarters"]})
            step += 1
            if progress:
                progress(step, total, f"{target} {q} {HORIZON_LABEL[h].lower()}")
    df = pd.DataFrame(rows)
    scores = []
    for (m, h), g in df.groupby(["model", "horizon"]):
        g = g[g["train"] >= 4]
        if len(g) < 3:
            continue
        b = df[(df.model == "benchmark") & (df.horizon == h) & df.quarter.isin(g.quarter)]
        rmse = float(np.sqrt((g.error ** 2).mean()))
        b_rmse = float(np.sqrt((b.error ** 2).mean())) if len(b) else None
        scores.append({"model": m, "horizon": h, "n": len(g), "rmse": round(rmse, 3),
                       "mae": round(float(g.error.abs().mean()), 3),
                       "rel_rmse": round(rmse / b_rmse, 3) if b_rmse else None,
                       "direction": round(float((np.sign(g.nowcast - g.nowcast.mean()) ==
                                                 np.sign(g.actual - g.actual.mean())).mean()), 3)})
    return {"rows": rows, "scores": scores}


def path(target: str, quarter: pd.Period, start: pd.Timestamp, end: pd.Timestamp, progress=None, step0=0,
         total=1) -> list[dict]:
    pts, step = [], step0
    for d in pd.date_range(start, end, freq="7D"):
        out = models.nowcast(target, quarter, d)
        pts.append({"as_of": str(d.date()), **{m: round(v["value"], 3) for m, v in out["models"].items()}})
        step += 1
        if progress:
            progress(step, total, f"{target} {quarter} path {d.date()}")
    return pts


def champion(scores: list[dict]) -> dict | None:
    cands = [s for s in scores if s["horizon"] == "after" and s["model"] != "benchmark"]
    return min(cands, key=lambda s: s["rmse"]) if cands else None


def run(progress=None, targets=("non_oil", "real")) -> dict:
    t0 = time.time()
    today = pd.Timestamp.now().normalize()
    rec = data.target_record()
    released = rec.dropna(subset=["release_date"])
    last_q = released["period"].max()
    pending, current = last_q + 1, pd.Period(today, "Q")
    quarters = [pending] + ([current] if current != pending else [])
    shock_q = pd.Period("2026Q2", "Q")  # the quarter that tests the models: the first contraction in the record
    n_bt = sum(len(rec.dropna(subset=[c, "release_date"])) for c in ("non_oil_yoy", "real_gdp_yoy")) * len(HORIZONS)
    path_specs = [(shock_q, _q_start(shock_q), released.loc[released.period == shock_q, "release_date"].iloc[0])]
    path_specs += [(q, max(_q_start(q) - pd.Timedelta(days=30), today - pd.Timedelta(days=180)), today) for q in quarters]
    n_path = sum(len(pd.date_range(a, b, freq="7D")) for _, a, b in path_specs) * len(targets)
    total, step = n_bt + n_path, 0
    out: dict = {"created": time.time(), "today": str(today.date()), "targets": {}}
    for t in targets:
        bt = backtest(t, progress, step, total)
        step += len(rec.dropna(subset=["non_oil_yoy" if t == "non_oil" else "real_gdp_yoy", "release_date"])) * len(HORIZONS)
        rmse = {(s["model"], s["horizon"]): s["rmse"] for s in bt["scores"]}
        champ = champion(bt["scores"])
        paths = {}
        for q, a, b in path_specs:
            paths[str(q)] = path(t, q, a, b, progress, step, total)
            step += len(paths[str(q)])
        latest = {}
        for q in quarters:
            nc = models.nowcast(t, q, today)
            obs = nc.get("observed_months", {})
            h = "after" if today > (q + 1).asfreq("D", "start").to_timestamp() + pd.Timedelta(days=29) else \
                "end" if today >= (q + 1).asfreq("D", "start").to_timestamp() - pd.Timedelta(days=1) else "mid"
            vals = {}
            for m, v in nc["models"].items():
                sd = rmse.get((m, h)) or rmse.get((m, "after"))
                vals[m] = {"value": round(v["value"], 2),
                           "band70": [round(v["value"] - Z70 * sd, 2), round(v["value"] + Z70 * sd, 2)] if sd else None,
                           "band90": [round(v["value"] - Z90 * sd, 2), round(v["value"] + Z90 * sd, 2)] if sd else None}
            prior = models.nowcast(t, q, today - pd.Timedelta(days=28))
            moved = []
            cur_b, old_b = nc["models"].get("bridge", {}).get("detail", {}), prior["models"].get("bridge", {}).get("detail", {})
            for k, v in (cur_b.get("contrib") or {}).items():
                moved.append({"input": k, "label": data.INDICATORS[k][6], "now": round(v, 2),
                              "change": round(v - (old_b.get("contrib") or {}).get(k, 0.0), 2)})
            for name in ("factor", "midas", "news"):
                if name in nc["models"] and name in prior["models"]:
                    moved.append({"input": name, "label": models.MODELS[name], "now": None,
                                  "change": round(nc["models"][name]["value"] - prior["models"][name]["value"], 2)})
            latest[str(q)] = {"horizon": h, "models": vals, "observed_months": obs, "train_quarters": nc["train_quarters"],
                              "moved_4w": sorted(moved, key=lambda m: -abs(m["change"]))}
        out["targets"][t] = {"label": data.TARGETS[t], "backtest": bt, "champion": champ, "paths": paths,
                             "latest": latest, "pending": str(pending), "current": str(current),
                             "released": _released(released, t)}
    out["inputs"] = data.latest_inputs()
    out["seconds"] = round(time.time() - t0, 1)
    champ = out["targets"]["non_oil"]["champion"]
    out["run_id"] = registry.record("nowcast", {"targets": list(targets), "horizons": HORIZONS},
                                    {"champion_non_oil": champ, "seconds": out["seconds"]}, None, out["today"])
    kv.set("forecast:latest", out)
    return out


def _released(released: pd.DataFrame, t: str) -> list[dict]:
    col = "non_oil_yoy" if t == "non_oil" else "real_gdp_yoy"
    return [{"quarter": str(r["period"]), "value": float(r[col]), "release_date": str(r["release_date"].date()),
             "source": r["source_url"], "source_type": r["source_type"]}
            for r in released.to_dict("records") if not pd.isna(r[col])]


def latest() -> dict | None:
    return kv.get("forecast:latest")


def scenario(target: str, hormuz_ships: float, brent: float) -> dict:
    """Nowcast of the current quarter if Hormuz transits and Brent sit at these levels for its remaining months."""
    today = pd.Timestamp.now().normalize()
    q = pd.Period(today, "Q")
    pm = data.panel(today)
    months = pd.period_range(pd.Period(today, "M"), q.asfreq("M", "end"), freq="M")
    base_h, base_b = data.monthly("hormuz"), data.monthly("brent")
    pm = pm.reindex(pm.index.union(months))
    pm.index = pd.PeriodIndex(pm.index, freq="M")
    for m in months:
        ly = m - 12
        if ly in base_h.index:
            pm.loc[m, "hormuz"] = (hormuz_ships / base_h.loc[ly] - 1) * 100
        if ly in base_b.index:
            pm.loc[m, "brent"] = (brent / base_b.loc[ly] - 1) * 100
    pm = pm.ffill(limit=2)
    base = models.nowcast(target, q, today)
    alt = models.nowcast(target, q, today, pm=pm)
    return {"quarter": str(q), "assumption": {"hormuz_ships_per_day": hormuz_ships, "brent_usd": brent,
                                              "months": [str(m) for m in months]},
            "base": {m: round(v["value"], 2) for m, v in base["models"].items()},
            "scenario": {m: round(v["value"], 2) for m, v in alt["models"].items()}}
