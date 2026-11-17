"""Scenario and stress engine for an idea's tilt and the whole notional portfolio.

1. Historical replays: realised returns in past windows (history starts late 2016). Instruments that did not
   trade then are proxied by beta to the MSCI UAE ETF (UAE listings) or to SPY.
2. Factor shocks: moves in oil, rates, dollar, VIX and gold passed through each instrument's estimated macro betas.
   The Hormuz case is the same shock the Forecasting page's scenario uses (linked in phase 4).
3. Monte Carlo: block bootstrap of joint daily returns (10-day blocks), 2,000 paths over 63 trading days.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .. import registry
from . import reserve, risk

REPLAYS = {
    "2018 Q4 sell-off": ("2018-10-03", "2018-12-24"),
    "2019 Abqaiq attack": ("2019-09-13", "2019-09-17"),
    "COVID crash": ("2020-02-19", "2020-03-23"),
    "2022 rates shock": ("2022-01-03", "2022-10-12"),
    "2025 tariff shock": ("2025-04-02", "2025-04-08"),
}
SHOCKS = {
    "Hormuz closure, 30 days": {"oil": 0.40, "vix": 15.0, "rates": -0.25, "dollar": 0.03, "gold": 0.08},
    "Oil collapse": {"oil": -0.35, "vix": 8.0, "rates": -0.30, "dollar": 0.02, "gold": 0.02},
    "Rates +100 bp": {"oil": 0.0, "vix": 6.0, "rates": 1.00, "dollar": 0.03, "gold": -0.03},
    "Risk-off, dollar up": {"oil": -0.10, "vix": 20.0, "rates": -0.40, "dollar": 0.06, "gold": 0.05},
}


def _proxy(symbol: str) -> str:
    return "UAE" if symbol.endswith(".AE") else "SPY"


def _window_returns(symbols: list[str], start: str, end: str, rets: pd.DataFrame) -> dict[str, dict]:
    w = rets.loc[start:end]
    out = {}
    for s in symbols:
        col = w.get(s)
        if col is not None and col.notna().mean() > 0.9:
            out[s] = {"return_pct": round(float((1 + col.fillna(0)).prod() - 1) * 100, 2), "proxy": None}
        else:
            p = _proxy(s)
            full = rets[[s, p]].dropna()
            beta = float(full[s].cov(full[p]) / full[p].var()) if len(full) > 120 else 1.0
            pr = float((1 + w[p].fillna(0)).prod() - 1)
            out[s] = {"return_pct": round(beta * pr * 100, 2), "proxy": f"{p} × beta {beta:.2f}"}
    return out


def run(active: dict[str, float], subject: str | None = None, seed: int = 7,
        existing: dict[str, float] | None = None) -> dict:
    """`active`: the idea's active weights. `existing`: active weights of ideas already approved, included in the
    whole-portfolio figures but not in the idea's own active P&L."""
    bench = {s: w + (existing or {}).get(s, 0.0) for s, w in reserve.benchmark_weights().items()}
    for s, w in (existing or {}).items():
        bench.setdefault(s, w)
    syms = sorted(set(bench) | set(active) | {"SPY", "UAE"})
    rets = risk.returns(syms, lookback=None)
    notional = reserve.NOTIONAL_USD_BN

    def pnl(rmap: dict[str, float]) -> tuple[float, float]:
        act = sum(active.get(s, 0.0) * rmap.get(s, 0.0) for s in active) / 100      # fraction of portfolio
        tot = sum((bench.get(s, 0.0) + active.get(s, 0.0)) * rmap.get(s, 0.0) for s in syms) / 100
        return act, tot

    replays = []
    for name, (a, b) in REPLAYS.items():
        per = _window_returns(syms, a, b, rets)
        act, tot = pnl({s: v["return_pct"] for s, v in per.items()})
        replays.append({"name": name, "start": a, "end": b, "active_bp": round(act * 1e4, 1),
                        "active_usd_mn": round(act * notional * 1e3, 1), "portfolio_pct": round(tot * 100, 2),
                        "instruments": {s: per[s] for s in active},
                        "proxied": [s for s in active if per[s]["proxy"]]})

    betas = risk.macro_betas(syms)
    shocks = []
    for name, moves in SHOCKS.items():
        rmap, r2 = {}, {}
        for s in syms:
            b = betas.get(s)
            if not b:
                continue
            # betas are % return per unit move (FACTOR_UNIT_MOVE); scale to the scenario's move
            rmap[s] = sum(b["betas_pct"][k] * moves[k] / risk.FACTOR_UNIT_MOVE[k] for k in moves)
            r2[s] = b["r2"]
        act, tot = pnl(rmap)
        shocks.append({"name": name, "moves": moves, "active_bp": round(act * 1e4, 1),
                       "active_usd_mn": round(act * notional * 1e3, 1), "portfolio_pct": round(tot * 100, 2),
                       "instruments": {s: {"return_pct": round(rmap.get(s, 0.0), 2), "r2": r2.get(s)} for s in active}})

    # Monte Carlo on the last ~5 years of joint returns; gaps filled by proxy beta
    hist = rets.iloc[-1260:].copy()
    for s in active:
        if hist[s].isna().mean() > 0.0:
            p = _proxy(s)
            full = rets[[s, p]].dropna()
            beta = float(full[s].cov(full[p]) / full[p].var()) if len(full) > 120 else 1.0
            hist[s] = hist[s].fillna(beta * hist[p])
    hist = hist.fillna(0.0)
    a_vec = np.array([active.get(s, 0.0) for s in hist.columns])
    t_vec = np.array([bench.get(s, 0.0) + active.get(s, 0.0) for s in hist.columns])
    X = hist.values
    rng = np.random.default_rng(seed)
    n_paths, horizon, block = 2000, 63, 10
    starts = rng.integers(0, len(X) - block, size=(n_paths, int(np.ceil(horizon / block))))
    act_out, tot_out = np.empty(n_paths), np.empty(n_paths)
    for i in range(n_paths):
        path = np.concatenate([X[s:s + block] for s in starts[i]])[:horizon]
        act_out[i] = (np.prod(1 + path @ a_vec) - 1) if a_vec.any() else 0.0
        tot_out[i] = np.prod(1 + path @ t_vec) - 1
    q = [5, 25, 50, 75, 95]
    hist_bins = np.histogram(act_out * 1e4, bins=30)
    mc = {"paths": n_paths, "horizon_days": horizon, "block_days": block,
          "active_bp_percentiles": {f"p{k}": round(float(np.percentile(act_out, k) * 1e4), 1) for k in q},
          "portfolio_pct_percentiles": {f"p{k}": round(float(np.percentile(tot_out, k) * 100), 2) for k in q},
          "prob_active_loss": round(float((act_out < 0).mean()), 3),
          "active_es95_bp": round(float(-act_out[act_out <= np.percentile(act_out, 5)].mean() * 1e4), 1),
          "histogram": {"edges_bp": [round(float(e), 1) for e in hist_bins[1]], "counts": hist_bins[0].tolist()}}

    worst = min(replays + shocks, key=lambda d: d["active_bp"])
    out = {"replays": replays, "shocks": shocks, "monte_carlo": mc,
           "worst": {"name": worst["name"], "active_bp": worst["active_bp"], "active_usd_mn": worst["active_usd_mn"]},
           "notional_usd_bn": notional}
    out["run_id"] = registry.record("stress", {"active": active, "seed": seed},
                                    {"worst": out["worst"], "mc_p5_bp": mc["active_bp_percentiles"]["p5"]}, subject)
    return out
