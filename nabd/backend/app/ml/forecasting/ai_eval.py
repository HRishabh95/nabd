"""The GDP nowcast: one Kalman model, run with and without AI news, scored in pseudo real time and set against the IMF.

Two versions of the same state-space model (kalman.py) differ only in their inputs:
- kalman        hard data: shipping, trade volumes, UAE equities (the kind of model a central bank already runs)
- kalman_ai     hard data + AI news signals (an LLM's labels of UAE business headlines, ai_news.py)
A third, kalman_tone (hard data + GDELT tone), is scored too, to separate the value of an LLM from that of a
word-count sentiment score; the page does not show it.

So the gap in accuracy between the two is the value of the news signal. Every nowcast uses only data published by its
date; GDP is scored against FCSC first releases at three points in each quarter, with the model's own bands checked
against what was published. Forward, the model gives each quarter to the end of next year, and the full-year growth
they imply (with released quarters as published) is set against the IMF World Economic Outlook.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ...core.db import store as kv
from .. import registry
from . import ai_news, data, kalman

VARIANTS = list(kalman.VARIANTS)
SHOWN = ["kalman", "kalman_ai"]
SHOCK = pd.Period("2026Q2", "Q")
HORIZONS = {"mid": 45, "end": 91, "after": 121}  # days after the quarter starts: mid-quarter, its end, a month later


def _q_start(q: pd.Period) -> pd.Timestamp:
    return q.asfreq("D", "start").to_timestamp()


def label(name: str) -> str:
    if name == "gdp":
        return "Past GDP releases"
    if name == "reestimation":
        return "Model update on new data"
    return data.INDICATORS[name][6] if name in data.INDICATORS else name


def group(name: str) -> str:
    if name.startswith("ai_"):
        return "AI news"
    if name.startswith("news_"):
        return "News tone"
    if name in ("gdp", "reestimation"):
        return label(name)
    return "Hard data"


def _r(v, d=3):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), d)


# ---- track record -------------------------------------------------------------------------------------------------

def backtest(target: str, progress=None, step0: int = 0, total: int = 1) -> dict:
    rec = data.target_record()
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    rows, step = [], step0
    for _, r in rec.dropna(subset=[col, "release_date"]).iterrows():
        q, actual = r["period"], float(r[col])
        for h, days in HORIZONS.items():
            as_of = min(_q_start(q) + pd.Timedelta(days=days), r["release_date"] - pd.Timedelta(days=1))
            pm = data.panel(as_of)
            y = data.target(target, as_of, training=True)
            y = y[y.index < q]
            if len(y):
                rows.append({"quarter": str(q), "horizon": h, "as_of": str(as_of.date()), "model": "benchmark",
                             "nowcast": _r(y.iloc[-1]), "actual": actual, "error": _r(y.iloc[-1] - actual)})
            for v in VARIANTS:
                o = kalman.nowcast(target, q, as_of, v, pm)
                if o is None:
                    continue
                rows.append({"quarter": str(q), "horizon": h, "as_of": str(as_of.date()), "model": v,
                             "nowcast": _r(o["value"]), "actual": actual, "error": _r(o["value"] - actual),
                             "lo70": _r(o["band70"][0]), "hi70": _r(o["band70"][1]),
                             "lo90": _r(o["band90"][0]), "hi90": _r(o["band90"][1])})
            step += 1
            if progress:
                progress(step, total, f"{target} {q} {h}")
    return {"rows": rows, "scores": scores(rows)}


def scores(rows: list[dict]) -> list[dict]:
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    out = []
    models = df[df.model.isin(VARIANTS)]
    have = models.groupby(["quarter", "horizon"]).model.nunique()
    for h in HORIZONS:  # every model scored on the same quarters: those where all versions produced a nowcast
        qs = [q for (q, hh), n in have.items() if hh == h and n == models.model.nunique()]
        g = df[(df.horizon == h) & df.quarter.isin(qs)]
        b = g[g.model == "benchmark"]
        b_rmse = float(np.sqrt((b.error ** 2).mean())) if len(b) else None
        for m, gm in g.groupby("model"):
            e = gm.error.astype(float)
            calm = gm[gm.quarter != str(SHOCK)].error.astype(float)
            rmse = float(np.sqrt((e ** 2).mean()))
            row = {"model": m, "horizon": h, "n": int(len(gm)), "rmse": _r(rmse), "mae": _r(e.abs().mean()),
                   "rel_rmse": _r(rmse / b_rmse) if b_rmse else None,
                   "rmse_excl_shock": _r(np.sqrt((calm ** 2).mean())) if len(calm) else None,
                   "shock_error": _r(gm[gm.quarter == str(SHOCK)].error.iloc[0]) if (gm.quarter == str(SHOCK)).any()
                   else None}
            if m != "benchmark":
                row["cover70"] = int(((gm.actual >= gm.lo70) & (gm.actual <= gm.hi70)).sum())
                row["cover90"] = int(((gm.actual >= gm.lo90) & (gm.actual <= gm.hi90)).sum())
            out.append(row)
    return out


def track(rows: list[dict], horizon: str = "after") -> list[dict]:
    """Per released quarter: the first release and what each model said a month after the quarter ended."""
    out: dict[str, dict] = {}
    for r in rows:
        if r["horizon"] != horizon or r["model"] not in SHOWN:
            continue
        out.setdefault(r["quarter"], {"quarter": r["quarter"], "actual": r["actual"], "as_of": r["as_of"]})[r["model"]] = r["nowcast"]
    return [out[q] for q in sorted(out)]


def track_full(target: str, today: pd.Timestamp) -> list[dict]:
    """What each model said a month after every quarter (or the day before its first release, if sooner), from the
    first quarter with enough history to the last one that has ended, whether or not FCSC's figure was found. Each row
    carries the first release where there is one, and FCSC's later estimate where only that was found."""
    rec = data.target_record().set_index("period")
    later = data.later_vintage().set_index("period")
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    first = pd.Period("2021Q4", "Q")
    last = pd.Period(today - pd.Timedelta(days=31), "Q") - 1
    out = []
    for q in pd.period_range(first, last, freq="Q"):
        as_of = (q + 1).asfreq("D", "start").to_timestamp() + pd.Timedelta(days=30)
        rel = rec.loc[q, "release_date"] if q in rec.index else pd.NaT
        if pd.notna(rel):
            as_of = min(as_of, rel - pd.Timedelta(days=1))
        pm = data.panel(as_of)
        row: dict = {"quarter": str(q), "as_of": str(as_of.date())}
        for v in SHOWN:
            o = kalman.nowcast(target, q, as_of, v, pm)
            row[v] = _r(o["value"], 2) if o else None
        actual = rec.loc[q, col] if q in rec.index and pd.notna(rel) else np.nan
        row["actual"] = _r(actual, 2) if pd.notna(actual) else None
        if row["actual"] is None and q in later.index and pd.notna(later.loc[q, col]):
            row["later"] = _r(later.loc[q, col], 2)
        out.append(row)
    return out


# ---- now and forward ------------------------------------------------------------------------------------------------

def _waterfall(target: str, q: pd.Period, a: pd.Timestamp, b: pd.Timestamp, variant: str = "kalman_ai") -> dict | None:
    r = kalman.revision(target, q, a, b, variant)
    if r is None:
        return None
    steps = [{"input": s["input"], "label": label(s["input"]), "group": group(s["input"]), "change": _r(s["change"])}
             for s in r["steps"]]
    steps = sorted([s for s in steps if abs(s["change"] or 0) >= 0.005], key=lambda s: -abs(s["change"]))
    return {"from_date": str(a.date()), "to_date": str(b.date()), "from": _r(r["from"], 2), "to": _r(r["to"], 2),
            "steps": steps}


def latest(target: str, q: pd.Period, today: pd.Timestamp) -> dict:
    pm = data.panel(today)
    out: dict = {"models": {}}
    for v in VARIANTS:
        o = kalman.nowcast(target, q, today, v, pm, detail=True)
        if o is None:
            continue
        out["models"][v] = {"value": _r(o["value"], 2), "sd": _r(o["sd"], 2),
                            "band70": [_r(x, 2) for x in o["band70"]], "band90": [_r(x, 2) for x in o["band90"]],
                            "mu": _r(o["detail"]["mu"], 2), "beta": o["detail"]["beta"],
                            "contrib": sorted([{"input": k, "label": label(k), "group": group(k), "value": _r(c)}
                                               for k, c in o["contrib"].items()], key=lambda x: -abs(x["value"]))}
    out["week"] = _waterfall(target, q, today - pd.Timedelta(days=7), today)
    out["month"] = _waterfall(target, q, today - pd.Timedelta(days=28), today)
    out["since_start"] = _waterfall(target, q, max(_q_start(q) - pd.Timedelta(days=30), pd.Timestamp("2020-01-01")), today)
    return out


def forecasts(target: str, today: pd.Timestamp, first: pd.Period, last: pd.Period) -> dict[str, list[dict]]:
    """Each model's value for every quarter from `first` to `last`, using data published by today. Beyond the data the
    factors fade back to average, so the far quarters lean on average growth and GDP's own persistence."""
    pm = data.panel(today)
    out: dict[str, list[dict]] = {v: [] for v in SHOWN}
    for q in pd.period_range(first, last, freq="Q"):
        for v in SHOWN:
            o = kalman.nowcast(target, q, today, v, pm)
            if o:
                out[v].append({"quarter": str(q), "value": _r(o["value"], 2), "lo70": _r(o["band70"][0], 2),
                               "hi70": _r(o["band70"][1], 2), "sd": _r(o["sd"], 2)})
    return out


def annual(fc: dict[str, list[dict]], released: list[dict], years: list[int], imf: list[dict]) -> list[dict]:
    """Full-year growth, approximated as the average of the four quarterly y/y rates: published quarters as released,
    the rest from the model. For the IMF, also what the unpublished quarters would have to average to match it."""
    official = {r["quarter"]: r["value"] for r in released}
    out = []
    for y in years:
        qs = [f"{y}Q{i}" for i in range(1, 5)]
        row: dict = {"year": y, "official": {q: official[q] for q in qs if q in official}, "models": {}}
        for v, pts in fc.items():
            by = {p["quarter"]: p for p in pts}
            if not all(q in official or q in by for q in qs):
                continue
            vals = [official.get(q, by.get(q, {}).get("value")) for q in qs]
            lo = [official.get(q, by.get(q, {}).get("lo70")) for q in qs]
            hi = [official.get(q, by.get(q, {}).get("hi70")) for q in qs]
            row["models"][v] = {"value": _r(np.mean(vals), 2), "lo70": _r(np.mean(lo), 2), "hi70": _r(np.mean(hi), 2),
                                "quarters": {q: {"value": _r(vals[i], 2), "official": q in official} for i, q in enumerate(qs)}}
        row["imf"] = [dict(r) for r in imf if r["year"] == y]
        rest = [q for q in qs if q not in official]
        for r in row["imf"]:
            r["needed_rest"] = _r((4 * r["value"] - sum(official[q] for q in qs if q in official)) / len(rest), 2) \
                if rest else None
        row["rest"] = rest
        out.append(row)
    return out


def signal_chart() -> dict:
    out: dict = {"months": [], "nonoil": [], "oil": []}
    try:
        no, oil = data.monthly("ai_nonoil"), data.monthly("ai_oil")
    except FileNotFoundError:
        return out
    idx = no.index.union(oil.index)
    out["months"] = [str(m) for m in idx]
    out["nonoil"] = [_r(no.get(m), 3) for m in idx]
    out["oil"] = [_r(oil.get(m), 3) for m in idx]
    return out


def run(progress=None, targets=("non_oil", "real")) -> dict:
    t0 = time.time()
    today = pd.Timestamp.now().normalize()
    rec = data.target_record()
    released = rec.dropna(subset=["release_date"])
    pending = released["period"].max() + 1
    current = pd.Period(today, "Q")
    quarters = [pending] + ([current] if current != pending else [])
    horizon_end = pd.Period(f"{today.year + 1}Q4", "Q")
    n_bt = sum(len(rec.dropna(subset=[c, "release_date"])) for c in ("non_oil_yoy", "real_gdp_yoy")) * len(HORIZONS)
    total, step = n_bt, 0
    imf = data.imf_forecasts()
    out: dict = {"created": time.time(), "today": str(today.date()), "variants": kalman.VARIANTS, "targets": {},
                 "imf": imf}
    for t in targets:
        col = "non_oil_yoy" if t == "non_oil" else "real_gdp_yoy"
        bt = backtest(t, progress, step, total)
        step += len(rec.dropna(subset=[col, "release_date"])) * len(HORIZONS)
        rel = [{"quarter": str(r["period"]), "value": float(r[col]), "release_date": str(r["release_date"].date())}
               for r in released.to_dict("records") if not pd.isna(r[col])]
        fc = forecasts(t, today, pending, horizon_end)
        out["targets"][t] = {
            "label": data.TARGETS[t], "backtest": bt, "track": track_full(t, today), "pending": str(pending),
            "current": str(current), "shock": str(SHOCK), "released": rel, "forecast": fc,
            "latest": {str(q): latest(t, q, today) for q in quarters},
            "annual": annual(fc, rel, [today.year, today.year + 1], imf if t == "real" else [])}
        if progress:
            progress(step, total, f"{t}: forecasts done")
    out["signal"] = signal_chart()
    out["months"] = ai_news.monthly_summary()
    out["archive"] = {"headlines": ai_news.archive_size(), "last_update": kv.get("ai_news:last")}
    out["seconds"] = round(time.time() - t0, 1)
    best = {s["horizon"]: s for s in out["targets"]["non_oil"]["backtest"]["scores"] if s["model"] == "kalman_ai"}
    out["run_id"] = registry.record("nowcast", {"variants": VARIANTS, "horizons": HORIZONS},
                                    {"kalman_ai_non_oil": best, "seconds": out["seconds"]}, None, out["today"])
    kv.set("forecast:kalman", out)
    return out


def stored() -> dict | None:
    return kv.get("forecast:kalman")


def headline(target: str = "non_oil") -> dict | None:
    """The few numbers other screens need: the next two quarters with and without AI, and the last release."""
    out = stored()
    if not out or target not in out["targets"]:
        return None
    t = out["targets"][target]

    def val(q, v):
        return ((t["latest"].get(q) or {}).get("models", {}).get(v) or {})
    return {"pending": t["pending"], "current": t["current"], "run_ts": out["created"], "run_id": out["run_id"],
            "pending_value": val(t["pending"], "kalman_ai").get("value") or val(t["pending"], "kalman").get("value"),
            "current_value": val(t["current"], "kalman_ai").get("value") or val(t["current"], "kalman").get("value"),
            "pending_band70": val(t["pending"], "kalman_ai").get("band70"),
            "last_official": t["released"][-1] if t["released"] else None,
            "scores": [s for s in t["backtest"]["scores"] if s["model"] in SHOWN + ["benchmark"]]}
