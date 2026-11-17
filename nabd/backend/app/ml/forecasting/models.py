"""Nowcast models for UAE quarterly GDP growth (y/y), built for a short target history.

The target has about 16 quarterly observations, while the indicators run monthly from 2019. So the models lean on the
indicators' long history and keep the link to GDP to two or three parameters:

- benchmark   Last release: next quarter's growth equals the latest published growth.
- factor      Dynamic factor model: one monthly activity factor from the indicator panel (statsmodels
              DynamicFactorMQ, which handles missing months and the ragged edge), bridged to GDP by a regression on
              its quarterly average.
- midas       MIDAS: GDP on the factor's last six months with exponential Almon weights (shape chosen on training).
- bridge      Ridge regression on quarterly averages of four core indicators (ports, Hormuz, UAE equities, Brent).
- news        Ridge regression on news tone (UAE economy) and news volume (Hormuz), from GDELT.
- ensemble    Equal-weight average of the four models above (benchmark excluded).

Gradient-boosted trees are not used: with ~16 target points they memorise rather than learn.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from . import data

logging.getLogger("statsmodels").setLevel(logging.ERROR)

MODELS = {
    "benchmark": "Last release (benchmark)",
    "factor": "Dynamic factor model",
    "midas": "MIDAS on the factor",
    "bridge": "Bridge regression",
    "news": "News model",
    "ensemble": "Ensemble",
}
# Real activity only: with rates, the dollar and the VIX in the panel, the factor tracked the global financial
# cycle (peaking in 2023) and missed the 2026 shipping collapse entirely.
FACTOR_INPUTS = ["hormuz", "ports", "imports", "exports", "uae_equity", "emaar", "enbd"]
BRIDGE_INPUTS = ["ports", "hormuz", "uae_equity", "brent"]
NEWS_INPUTS = ["news_uae_tone", "news_hormuz_vol"]


def activity_factor(pm: pd.DataFrame) -> pd.Series:
    """One monthly factor from the standardised indicator panel; sign set so it rises with port calls."""
    from statsmodels.tsa.statespace.dynamic_factor_mq import DynamicFactorMQ

    x = pm[[c for c in FACTOR_INPUTS if c in pm]].loc["2020-01":]
    x = x.dropna(axis=1, thresh=int(0.6 * len(x)))
    z = (x - x.mean()) / x.std()
    z.index = z.index.to_timestamp(how="end").normalize()
    z = z.asfreq("ME")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = DynamicFactorMQ(z, factors=1, factor_orders=1, idiosyncratic_ar1=False)
        res = mod.fit(disp=False, maxiter=60)
    f = pd.Series(np.asarray(res.factors.smoothed).ravel(), index=z.index)
    f.index = f.index.to_period("M")
    if "ports" in z and np.corrcoef(f.values, z["ports"].reindex(z.index).fillna(0).values)[0, 1] < 0:
        f = -f
    return f


def _fit_predict(X: pd.DataFrame, y: pd.Series, xq: pd.Series, alpha: float) -> tuple[float, dict]:
    Xs = X.loc[y.index]
    mu, sd = Xs.mean(), Xs.std().replace(0, 1)
    m = Ridge(alpha=alpha).fit(((Xs - mu) / sd).values, y.values)
    xz = ((xq - mu) / sd).values.reshape(1, -1)
    pred = float(m.predict(xz)[0])
    contrib = {c: float(m.coef_[i] * xz[0, i]) for i, c in enumerate(X.columns)}  # vs the training average
    return pred, {"intercept": float(m.intercept_), "contrib": contrib}


def almon(theta: float, n: int = 6) -> np.ndarray:
    w = np.exp(-theta * np.arange(n))
    return w / w.sum()


def nowcast(target_name: str, quarter: pd.Period, as_of: pd.Timestamp, factor: pd.Series | None = None,
            pm: pd.DataFrame | None = None) -> dict:
    """Nowcast of `quarter` using only data knowable on `as_of`. Returns each model's prediction and details."""
    pm = data.panel(as_of) if pm is None else pm
    y = data.target(target_name, as_of, training=True)
    y = y[y.index < quarter]
    out: dict = {"quarter": str(quarter), "as_of": str(as_of.date()), "train_quarters": len(y), "models": {}}
    if len(y) == 0:
        return out
    out["models"]["benchmark"] = {"value": float(y.iloc[-1]), "detail": {"last_release": str(y.index[-1])}}
    out["observed_months"] = data.months_observed(pm, quarter)
    if len(y) < 4:
        return out

    q = data.quarterly_features(pm.loc[:quarter.asfreq("M", "end")])
    # factor bridge
    try:
        f = activity_factor(pm) if factor is None else factor
        fq = f.groupby(f.index.asfreq("Q")).mean()
        fq_train = fq.reindex(y.index).dropna()
        if quarter in fq.index and len(fq_train) >= 4:
            yy = y.loc[fq_train.index]
            b = np.polyfit(fq_train.values, yy.values, 1)
            out["models"]["factor"] = {"value": float(np.polyval(b, fq.loc[quarter])),
                                       "detail": {"slope": float(b[0]), "factor_q": float(fq.loc[quarter])}}
            # MIDAS: last six months of the factor, Almon weights, shape chosen by in-sample fit
            best = None
            for th in (0.0, 0.3, 0.6, 1.0, 1.5):
                w = almon(th)

                def agg(qq, w=w):
                    end = qq.asfreq("M", "end")
                    vals = f.loc[:end].iloc[-6:]
                    return float(np.dot(w[: len(vals)][::-1] / w[: len(vals)].sum(), vals.values)) if len(vals) else np.nan
                xs = pd.Series({qq: agg(qq) for qq in fq_train.index}).dropna()
                if len(xs) < 4:
                    continue
                bb = np.polyfit(xs.values, y.loc[xs.index].values, 1)
                sse = float(((np.polyval(bb, xs.values) - y.loc[xs.index].values) ** 2).sum())
                if best is None or sse < best[0]:
                    best = (sse, th, bb, agg(quarter))
            if best:
                out["models"]["midas"] = {"value": float(np.polyval(best[2], best[3])), "detail": {"theta": best[1]}}
    except Exception as exc:  # the factor can fail on very short panels; the other models still run
        out["factor_error"] = str(exc)[:200]
    # bridge
    cols = [c for c in BRIDGE_INPUTS if c in q]
    X = q[cols].dropna()
    common = y.index.intersection(X.index)
    if quarter in X.index and len(common) >= 4:
        v, det = _fit_predict(X, y.loc[common], X.loc[quarter], alpha=2.0)
        out["models"]["bridge"] = {"value": v, "detail": det}
    # news
    ncols = [c for c in NEWS_INPUTS if c in q]
    if ncols:
        Xn = q[ncols].dropna()
        cn = y.index.intersection(Xn.index)
        if quarter in Xn.index and len(cn) >= 4:
            v, det = _fit_predict(Xn, y.loc[cn], Xn.loc[quarter], alpha=3.0)
            out["models"]["news"] = {"value": v, "detail": det}
    parts = [out["models"][k]["value"] for k in ("factor", "midas", "bridge", "news") if k in out["models"]]
    if parts:
        out["models"]["ensemble"] = {"value": float(np.mean(parts)), "detail": {"members": len(parts)}}
    return out
