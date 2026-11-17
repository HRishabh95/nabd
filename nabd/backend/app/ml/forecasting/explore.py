"""Let an economist test the nowcast: switch inputs on and off, and score CBUAE's own model on the same test.

- `with_inputs`  the Kalman model refitted on any chosen set of inputs: today's nowcasts, the forecast to the end of
                 next year, and the same pseudo real-time backtest (three points per quarter, first releases), next to
                 the default model, so the effect of each input is measured rather than asserted.
- `own_model`    CBUAE's nowcasts uploaded as a CSV (quarter, made_on, value). Each one is scored against the first
                 release at its point in the quarter, next to Kalman + AI news on the same dates, and next to the simple
                 average of the two (forecast combination: the usual way to add a new signal to an existing model).
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd

from ...core.db import store as kv
from . import data, kalman
from .ai_eval import HORIZONS, SHOCK, _q_start, _r


def _horizon(q: pd.Period, made: pd.Timestamp) -> str:
    days = (made - _q_start(q)).days
    return "mid" if days <= 60 else "end" if days <= 105 else "after"


def _score(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    out = []
    for h in HORIZONS:
        g = df[df.horizon == h].dropna(subset=cols)
        if not len(g):
            continue
        row = {"horizon": h, "n": int(len(g))}
        for c in cols:
            e = g[c] - g.actual
            calm = g[g.quarter != str(SHOCK)]
            row[c] = {"rmse": _r(np.sqrt((e ** 2).mean())), "mae": _r(e.abs().mean()),
                      "rmse_excl_shock": _r(np.sqrt(((calm[c] - calm.actual) ** 2).mean())) if len(calm) else None}
        out.append(row)
    return out


def with_inputs(target: str, inputs: list[str]) -> dict:
    inputs = [i for i in inputs if i in data.INDICATORS]
    today = pd.Timestamp.now().normalize()
    rec = data.target_record()
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    released = rec.dropna(subset=["release_date"])
    rows = []
    for _, r in rec.dropna(subset=[col, "release_date"]).iterrows():
        q = r["period"]
        for h, days in HORIZONS.items():
            as_of = min(_q_start(q) + pd.Timedelta(days=days), r["release_date"] - pd.Timedelta(days=1))
            pm = data.panel(as_of)
            mine = kalman.nowcast(target, q, as_of, pm=pm, inputs=inputs)
            base = kalman.nowcast(target, q, as_of, "kalman_ai", pm)
            rows.append({"quarter": str(q), "horizon": h, "actual": float(r[col]),
                         "mine": mine["value"] if mine else np.nan, "default": base["value"] if base else np.nan,
                         "mine_in70": bool(mine and mine["band70"][0] <= r[col] <= mine["band70"][1])})
    df = pd.DataFrame(rows)
    pm = data.panel(today)
    pending = released["period"].max() + 1
    quarters = pd.period_range(pending, pd.Period(f"{today.year + 1}Q4", "Q"), freq="Q")
    fc = []
    for q in quarters:
        mine = kalman.nowcast(target, q, today, pm=pm, inputs=inputs, detail=q == pd.Period(today, "Q"))
        base = kalman.nowcast(target, q, today, "kalman_ai", pm)
        fc.append({"quarter": str(q), "mine": _r(mine["value"], 2) if mine else None,
                   "lo70": _r(mine["band70"][0], 2) if mine else None, "hi70": _r(mine["band70"][1], 2) if mine else None,
                   "default": _r(base["value"], 2) if base else None,
                   "contrib": {k: _r(v) for k, v in (mine or {}).get("contrib", {}).items()} or None})
    ok = df.mine.notna().any()
    after = df[df.horizon == "after"].sort_values("quarter")
    track = [{"quarter": r.quarter, "actual": _r(r.actual, 2), "mine": _r(r.mine, 2) if pd.notna(r.mine) else None,
              "default": _r(r.default, 2) if pd.notna(r.default) else None} for r in after.itertuples()]
    return {"target": target, "inputs": inputs, "ok": bool(ok), "track": track,
            "message": None if ok else "Pick at least two shipping, trade or market inputs: the model needs a common factor.",
            "scores": _score(df, ["mine", "default"]) if ok else [],
            "cover70": {h: int(g.mine_in70.sum()) for h, g in df.groupby("horizon")} if ok else {},
            "forecast": fc, "labels": {k: data.INDICATORS[k][6] for k in data.INDICATORS}}


TEMPLATE_HELP = ("One row per nowcast your model made: quarter (e.g. 2025Q2), made_on (YYYY-MM-DD, the date it was "
                 "made) and value (% y/y). Several rows per quarter are fine, one for each date.")


def template(target: str) -> str:
    """A CSV for CBUAE to fill: the released quarters, at the three points Nabd scores."""
    rec = data.target_record()
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    lines = ["quarter,made_on,value"]
    for _, r in rec.dropna(subset=[col, "release_date"]).iterrows():
        q = r["period"]
        for days in HORIZONS.values():
            made = min(_q_start(q) + pd.Timedelta(days=days), r["release_date"] - pd.Timedelta(days=1))
            lines.append(f"{q},{made.date()},")
    return "\n".join(lines) + "\n"


def parse(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    if not {"quarter", "made_on", "value"} <= set(df.columns):
        raise ValueError("The file needs the columns quarter, made_on and value")
    df = df.dropna(subset=["value"])
    df["period"] = pd.PeriodIndex(df["quarter"].astype(str).str.replace(" ", ""), freq="Q")
    df["made_on"] = pd.to_datetime(df["made_on"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["made_on", "value"])
    if df.empty:
        raise ValueError("No rows with a quarter, a date and a value")
    return df


def own_model(target: str, text: str, name: str = "CBUAE model") -> dict:
    """Score uploaded nowcasts against first releases, next to Kalman + AI news on the same dates and their average."""
    up = parse(text)
    rec = data.target_record().set_index("period")
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    rows, skipped = [], 0
    for r in up.itertuples():
        if r.period not in rec.index or pd.isna(rec.loc[r.period, col]) or pd.isna(rec.loc[r.period, "release_date"]):
            skipped += 1
            continue
        if r.made_on >= rec.loc[r.period, "release_date"]:  # made after the official figure was out: not a nowcast
            skipped += 1
            continue
        ai = kalman.nowcast(target, r.period, r.made_on, "kalman_ai", data.panel(r.made_on))
        v_ai = ai["value"] if ai else np.nan
        rows.append({"quarter": str(r.period), "made_on": str(r.made_on.date()), "horizon": _horizon(r.period, r.made_on),
                     "actual": float(rec.loc[r.period, col]), "yours": float(r.value), "kalman_ai": v_ai,
                     "average": (float(r.value) + v_ai) / 2 if not np.isnan(v_ai) else np.nan})
    df = pd.DataFrame(rows)
    out = {"target": target, "name": name, "rows": len(df), "skipped": skipped,
           "scores": _score(df, ["yours", "kalman_ai", "average"]) if len(df) else [],
           "detail": [{k: (_r(v, 2) if isinstance(v, float) else v) for k, v in x.items()} for x in rows]}
    kv.set(f"forecast:own:{target}", out)
    return out


# ---- does the news help? ----------------------------------------------------------------------------------------------

AI_SERIES = ("ai_nonoil", "ai_oil")


def shock_replay(target: str) -> dict:
    """Week by week through the Q2 2026 quarter until FCSC published it: what each model said, and the actual."""
    from .ai_eval import SHOCK
    rec = data.target_record().set_index("period")
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    rel = rec.loc[SHOCK, "release_date"]
    pts = []
    for d in pd.date_range(_q_start(SHOCK) - pd.Timedelta(days=14), rel - pd.Timedelta(days=1), freq="7D"):
        pm = data.panel(d)
        row = {"as_of": str(d.date())}
        for v in ("kalman", "kalman_ai"):
            o = kalman.nowcast(target, SHOCK, d, v, pm)
            row[v] = _r(o["value"], 2) if o else None
        pts.append(row)
    return {"quarter": str(SHOCK), "actual": float(rec.loc[SHOCK, col]), "release": str(rel.date()), "points": pts}


def _rmse_ai(target: str) -> float:
    """Average error of Kalman + AI news over the three points of every scored quarter."""
    rec = data.target_record()
    col = "non_oil_yoy" if target == "non_oil" else "real_gdp_yoy"
    errs = []
    for _, r in rec.dropna(subset=[col, "release_date"]).iterrows():
        q = r["period"]
        for days in HORIZONS.values():
            as_of = min(_q_start(q) + pd.Timedelta(days=days), r["release_date"] - pd.Timedelta(days=1))
            o = kalman.nowcast(target, q, as_of, "kalman_ai", data.panel(as_of))
            if o:
                errs.append(o["value"] - float(r[col]))
    return float(np.sqrt(np.mean(np.square(errs)))) if errs else np.nan


def placebo(target: str = "non_oil", n: int = 40, seed: int = 11, progress=None) -> dict:
    """Is the news signal's help real or luck? Shuffle which month each news reading belongs to, re-score the model,
    and repeat. If the real news beats most shuffles, the timing of the news carries information."""
    real = _rmse_ai(target)
    full = {s: data.monthly(s) for s in AI_SERIES}
    original = data.monthly
    rng = np.random.default_rng(seed)
    shuffled = []
    try:
        for k in range(n):
            perm = {s: pd.Series(rng.permutation(v.values), index=v.index) for s, v in full.items()}

            def fake(name, as_of=None, _p=perm):
                if name in _p:
                    s = _p[name]
                    if as_of is not None:
                        lag = data.INDICATORS[name][5]
                        s = s[s.index <= (as_of - pd.Timedelta(days=lag)).to_period("M")]
                    return s
                return original(name, as_of)
            data.monthly = fake
            shuffled.append(_rmse_ai(target))
            if progress:
                progress(k + 1, n, f"shuffle {k + 1} of {n}")
    finally:
        data.monthly = original
    sh = np.array([x for x in shuffled if np.isfinite(x)])
    better = int((sh <= real).sum())
    out = {"target": target, "n": int(len(sh)), "real_rmse": _r(real), "shuffled": [_r(x) for x in sh],
           "shuffled_median": _r(np.median(sh)) if len(sh) else None, "shuffles_as_good": better,
           "p_value": _r((better + 1) / (len(sh) + 1)), "created": pd.Timestamp.now().isoformat()}
    kv.set(f"forecast:placebo:{target}", out)
    return out
