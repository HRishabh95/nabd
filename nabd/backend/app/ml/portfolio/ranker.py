"""Return-ranking model: cross-sectional gradient-boosted trees, trained walk-forward each month.

Target: the instrument's next-63-trading-day return minus SPY's, ranked across instruments on each date.
Features (ranked across instruments on each date): 12-1 month momentum, 3-month momentum, 1-year volatility,
1-year max drawdown, distance from 1-year high, 1-year beta to SPY, 1-year oil and rate sensitivity, and the
regime model's stress probability (the same for all instruments on a date, so trees can condition on it).

Validation is strictly out of sample: the model used at month m was trained only on dates whose 63-day target
had fully realised before m. Reported: mean rank IC, its t-statistic, hit rate (months with IC > 0) and the
top-minus-bottom quintile return spread.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

from ...core.db import store as kv
from ...data import store
from ...data.universe import UNIVERSE
from .. import registry
from .regime import stress_prob_series

HORIZON = 63
FEATURES = ["mom_12_1", "mom_3", "vol_1y", "dd_1y", "dist_high", "beta_spy", "beta_oil", "beta_rates", "stress"]
FEATURE_LABELS = {"mom_12_1": "12-1 month momentum", "mom_3": "3-month momentum", "vol_1y": "1-year volatility",
                  "dd_1y": "1-year drawdown", "dist_high": "Distance from 1-year high", "beta_spy": "Beta to US market",
                  "beta_oil": "Oil sensitivity", "beta_rates": "Rate sensitivity", "stress": "Market stress probability"}


def universe() -> list[str]:
    return [i.symbol for i in UNIVERSE if i.asset == "equity"]


def panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long feature frame (date, symbol) with features and target, plus the price panel."""
    syms = universe()
    px = store.close_panel(syms).ffill(limit=3)
    r = px.pct_change(fill_method=None)
    spy = r["SPY"]
    oil = store.read_series("fred", "DCOILBRENTEU").set_index("date")["value"].reindex(px.index).ffill().pct_change(
        fill_method=None)
    rates = store.read_series("fred", "DGS10").set_index("date")["value"].reindex(px.index).ffill().diff()

    month_ends = px.groupby(px.index.to_period("M")).tail(1).index
    month_ends = month_ends[month_ends >= px.index[260]]
    var_spy, var_oil, var_rates = (spy.rolling(252).var(), oil.rolling(252).var(), rates.rolling(252).var())
    feats = {
        "mom_12_1": px.shift(21) / px.shift(252) - 1,
        "mom_3": px / px.shift(63) - 1,
        "vol_1y": r.rolling(252).std() * np.sqrt(252),
        "dd_1y": px / px.rolling(252).max() - 1,
        "dist_high": px / px.rolling(252).max() - 1,
        "beta_spy": r.rolling(252).cov(spy).div(var_spy, axis=0),
        "beta_oil": r.rolling(252).cov(oil).div(var_oil, axis=0),
        "beta_rates": r.rolling(252).cov(rates).div(var_rates, axis=0),
    }
    # drawdown: worst point of the trailing year, not just today's distance from the high
    feats["dd_1y"] = (px / px.rolling(252, min_periods=200).max() - 1).rolling(252, min_periods=200).min()
    fwd = px.shift(-HORIZON) / px - 1
    target = fwd.sub(fwd["SPY"], axis=0)
    stress = stress_prob_series().reindex(px.index, method="ffill")

    rows = []
    for d in month_ends:
        f = pd.DataFrame({k: v.loc[d] for k, v in feats.items()})
        f["target"] = target.loc[d]
        f["fwd_rel"] = target.loc[d]
        f = f.dropna(subset=FEATURES[:-1])
        if len(f) < 30:
            continue
        ranked = f[FEATURES[:-1]].rank(pct=True)
        ranked["stress"] = float(stress.loc[d]) if not np.isnan(stress.loc[d]) else 0.0
        ranked["target"] = f["target"].rank(pct=True)
        ranked["fwd_rel"] = f["fwd_rel"]
        ranked["date"], ranked["symbol"] = d, f.index
        rows.append(ranked.reset_index(drop=True))
    return pd.concat(rows, ignore_index=True), px


def _model():
    return HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_depth=3, min_samples_leaf=80,
                                         l2_regularization=1.0, random_state=7)


def train(progress=None) -> dict:
    t0 = time.time()
    df, px = panel()
    dates = sorted(df["date"].unique())
    idx = {d: i for i, d in enumerate(px.index)}
    ics, spreads, preds_oos = [], [], []
    test_dates = [d for d in dates if d >= pd.Timestamp("2019-06-30")]
    for k, d in enumerate(test_dates):
        # train only on rows whose 63-day target was fully known by date d
        cutoff = px.index[max(idx[d] - HORIZON, 0)]
        tr = df[(df["date"] <= cutoff) & df["target"].notna()]
        te = df[(df["date"] == d)]
        if len(tr) < 1000:
            continue
        m = _model().fit(tr[FEATURES], tr["target"])
        p = m.predict(te[FEATURES])
        realised = te["fwd_rel"]
        ok = realised.notna()
        if ok.sum() >= 20:
            ic = spearmanr(p[ok], realised[ok]).statistic
            q = pd.qcut(pd.Series(p[ok]).rank(method="first"), 5, labels=False)
            rr = realised[ok].reset_index(drop=True)
            spreads.append(float(rr[q == 4].mean() - rr[q == 0].mean()))
            ics.append(float(ic))
            preds_oos.append({"date": str(pd.Timestamp(d).date()), "ic": round(float(ic), 3)})
        if progress:
            progress(k + 1, len(test_dates), str(pd.Timestamp(d).date()))
    ics_a = np.array(ics)
    metrics = {
        "months": len(ics), "mean_ic": round(float(ics_a.mean()), 3),
        "ic_t_stat": round(float(ics_a.mean() / (ics_a.std(ddof=1) / np.sqrt(len(ics_a)))), 2),
        "hit_rate": round(float((ics_a > 0).mean()), 3),
        "top_minus_bottom_quintile_3m_pct": round(float(np.mean(spreads)) * 100, 2),
        "seconds": round(time.time() - t0, 1),
    }
    # final model on all realised data, used for today's ranks
    final = _model().fit(df[df["target"].notna()][FEATURES], df[df["target"].notna()]["target"])
    last = df[df["date"] == dates[-1]].copy()
    last["score"] = final.predict(last[FEATURES])
    last["rank_pct"] = last["score"].rank(pct=True)
    importance = _importance(final, df[df["target"].notna()])
    run_id = registry.record("ranker", {"features": FEATURES, "horizon_days": HORIZON}, metrics, None,
                             str(pd.Timestamp(dates[-1]).date()))
    result = {"run_id": run_id, "as_of": str(pd.Timestamp(dates[-1]).date()), "metrics": metrics,
              "ic_history": preds_oos, "importance": importance,
              "ranks": {r["symbol"]: {"rank_pct": round(float(r["rank_pct"]), 3),
                                      **{f: round(float(r[f]), 3) for f in FEATURES}}
                        for r in last.to_dict("records")}}
    kv.set("ranker:latest", result)
    return result


def _importance(model, df: pd.DataFrame) -> list[dict]:
    """Permutation importance on a sample (drop in rank correlation when a feature is shuffled)."""
    rng = np.random.default_rng(7)
    s = df.sample(min(len(df), 8000), random_state=7)
    base = spearmanr(model.predict(s[FEATURES]), s["target"]).statistic
    out = []
    for f in FEATURES:
        x = s[FEATURES].copy()
        x[f] = rng.permutation(x[f].values)
        out.append({"feature": f, "label": FEATURE_LABELS[f],
                    "importance": round(float(base - spearmanr(model.predict(x), s["target"]).statistic), 4)})
    return sorted(out, key=lambda d: -d["importance"])


def latest() -> dict | None:
    return kv.get("ranker:latest")
