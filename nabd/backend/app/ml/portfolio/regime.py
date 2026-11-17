"""Market regime model: a three-state Gaussian HMM on weekly market and macro features.

States are labelled after fitting by their average VIX: calm, normal, stress.
"""

from __future__ import annotations

import functools
import logging
import warnings

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from ...data import store
from .. import registry
from .risk import _cache_key

logging.getLogger("hmmlearn").setLevel(logging.ERROR)  # convergence chatter
LABELS = ["calm", "normal", "stress"]
EPISODES = {"2018 Q4 sell-off": ("2018-10-01", "2018-12-31"), "COVID crash": ("2020-02-20", "2020-04-30"),
            "2022 rates shock": ("2022-01-01", "2022-10-31")}


def features() -> pd.DataFrame:
    spy = store.read_series("yahoo", "SPY").set_index("date")["adjclose"]
    vix = store.read_series("fred", "VIXCLS").set_index("date")["value"]
    # Credit stress: corporate bonds against Treasuries of similar duration. FRED serves only 3 years of ICE's
    # high-yield spread (licence), so the 10-year price history of LQD and IEF stands in.
    lqd = store.read_series("yahoo", "LQD").set_index("date")["adjclose"]
    ief = store.read_series("yahoo", "IEF").set_index("date")["adjclose"]
    w = pd.DataFrame({"spy": spy, "vix": vix, "lqd": lqd, "ief": ief}).ffill().resample("W-FRI").last().dropna()
    credit = (np.log(w["lqd"]).diff() - np.log(w["ief"]).diff()) * 100
    return pd.DataFrame({"ret": np.log(w["spy"]).diff() * 100, "logvix": np.log(w["vix"]), "credit": credit},
                        index=w.index).dropna()


@functools.lru_cache(maxsize=2)
def _fit(key: float) -> dict:
    X = features()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        best = None
        for seed in range(5):  # a few restarts; keep the best likelihood
            m = GaussianHMM(n_components=3, covariance_type="full", n_iter=300, random_state=seed).fit(X.values)
            ll = m.score(X.values)
            if best is None or ll > best[0]:
                best = (ll, m)
    ll, m = best
    post = m.predict_proba(X.values)
    order = np.argsort(m.means_[:, 1])  # by mean log VIX: calm < normal < stress
    probs = pd.DataFrame(post[:, order], index=X.index, columns=LABELS)
    stress = probs["stress"]
    overlap = {k: round(float(stress.loc[a:b].mean()), 2) for k, (a, b) in EPISODES.items()}
    trans = m.transmat_[np.ix_(order, order)]
    current = probs.iloc[-1].round(3).to_dict()
    metrics = {"log_likelihood": round(float(ll), 1), "weeks": len(X), "stress_in_episodes": overlap,
               "persistence": {LABELS[i]: round(float(trans[i, i]), 3) for i in range(3)}, "current": current}
    run_id = registry.record("regime", {"features": list(X.columns), "states": 3}, metrics, None,
                             str(X.index[-1].date()))
    return {"run_id": run_id, "current": current, "as_of": str(X.index[-1].date()),
            "state": max(current, key=current.get), "metrics": metrics,
            "history": [{"date": str(d.date()), **{k: round(float(v), 3) for k, v in row.items()}}
                        for d, row in probs.iloc[-156:].iterrows()],
            "probs": probs}


def regime() -> dict:
    out = dict(_fit(_cache_key()))
    out.pop("probs")
    return out


def stress_prob_series() -> pd.Series:
    return _fit(_cache_key())["probs"]["stress"]
