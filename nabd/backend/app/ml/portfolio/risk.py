"""Risk model: returns, covariance, tracking error, budget use, marginal risk, VaR/ES, macro betas."""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from ...data import store
from .. import registry
from . import reserve

LOOKBACK = 756          # ~3 years of trading days
HALF_LIFE = 126         # days, for the exponential weights
FACTORS = {             # name: (source, series, transform)
    "oil": ("fred", "DCOILBRENTEU", "pct"),
    "rates": ("fred", "DGS10", "diff"),      # change in 10y yield, percentage points
    "dollar": ("fred", "DTWEXBGS", "pct"),
    "vix": ("fred", "VIXCLS", "diff"),
    "gold": ("yahoo", "GLD", "pct"),
}
FACTOR_LABELS = {"oil": "Brent +10%", "rates": "10y yield +50 bp", "dollar": "Dollar +5%", "vix": "VIX +10 pts",
                 "gold": "Gold +10%"}
FACTOR_UNIT_MOVE = {"oil": 0.10, "rates": 0.50, "dollar": 0.05, "vix": 10.0, "gold": 0.10}


def _cache_key() -> float:
    """Changes whenever prices are refreshed, so cached fits are reused only on unchanged data."""
    rows = [r for r in store.catalog() if r["source"] == "yahoo"]
    return max((r["last_refresh"] or 0) for r in rows) if rows else 0.0


def returns(symbols: list[str], lookback: int | None = LOOKBACK) -> pd.DataFrame:
    px = store.close_panel(sorted(set(symbols)))
    px = px.ffill(limit=3)  # bridge exchange holidays (UAE and US calendars differ)
    r = px.pct_change(fill_method=None)
    r = r.iloc[1:]
    if lookback:
        r = r.iloc[-lookback:]
    return r


def ewma_weights(n: int, half_life: int = HALF_LIFE) -> np.ndarray:
    w = 0.5 ** (np.arange(n)[::-1] / half_life)
    return w / w.sum()


@functools.lru_cache(maxsize=32)
def _cov_cached(symbols: tuple[str, ...], key: float) -> tuple[pd.DataFrame, dict]:
    r = returns(list(symbols))
    complete = r.dropna(axis=1, thresh=int(0.8 * len(r)))      # instruments with enough history
    complete = complete.fillna(0.0)
    w = ewma_weights(len(complete))
    x = (complete - (complete.T @ w)).mul(np.sqrt(w * len(w)), axis=0)  # EWMA reweighting
    lw = LedoitWolf().fit(x.values)
    cov = pd.DataFrame(lw.covariance_ * 252, index=complete.columns, columns=complete.columns)
    info = {"shrinkage": round(float(lw.shrinkage_), 3), "days": len(complete),
            "start": str(complete.index[0].date()), "end": str(complete.index[-1].date()),
            "dropped": sorted(set(symbols) - set(complete.columns))}
    return cov, info


def covariance(symbols: list[str]) -> tuple[pd.DataFrame, dict]:
    return _cov_cached(tuple(sorted(set(symbols))), _cache_key())


def active_from_tilt(tilt: dict[str, float], funding: str = "equity") -> dict[str, float]:
    """Active weights (fractions of the portfolio) for a tilt. `tilt` maps symbol -> weight in % of portfolio.
    The tilt is funded from the benchmark equity sleeve pro rata (a relative bet within equities), or from cash.
    A net cut sends its proceeds to Treasury bills, or with funding "mandate" back into the equity mandates."""
    a = {s: v / 100 for s, v in tilt.items()}
    total = sum(a.values())
    if total >= 0:  # net buying is funded from the chosen source, pro rata
        source = reserve.equity_sleeve() if funding == "equity" else {"SHV": 1.0}
        for s, share in source.items():
            a[s] = a.get(s, 0.0) - total * share
    elif funding == "mandate":  # net selling, proceeds reinvested across the equity mandates (less of one name)
        for s, share in reserve.equity_sleeve().items():
            a[s] = a.get(s, 0.0) - total * share
    else:  # net selling (a reduce idea): the proceeds sit in Treasury bills until redeployed
        a["SHV"] = a.get("SHV", 0.0) - total
    return a


def analyse(active: dict[str, float], existing_active: dict[str, float] | None = None, subject: str | None = None) -> dict:
    """Ex-ante risk of a set of active weights on top of the benchmark (and any existing active positions)."""
    bench = reserve.benchmark_weights()
    existing = existing_active or {}
    symbols = sorted(set(bench) | set(active) | set(existing))
    cov, info = covariance(symbols)
    missing = [s for s in active if s not in cov.index]
    syms = list(cov.index)

    def vec(d):
        return np.array([d.get(s, 0.0) for s in syms])

    a_new, a_old, b = vec(active), vec(existing), vec(bench)
    a_tot = a_new + a_old
    S = cov.values
    te = lambda a: float(np.sqrt(max(a @ S @ a, 0.0)))  # noqa: E731
    te_before, te_after, te_alone = te(a_old), te(a_tot), te(a_new)
    mctr = (S @ a_tot) / te_after if te_after > 0 else np.zeros(len(syms))
    contrib = a_tot * mctr
    budget = reserve.ACTIVE_RISK_BUDGET_BP / 1e4

    # historical VaR / ES of the active P&L and of the total portfolio, last 3 years, 1-day
    r = returns(syms).fillna(0.0)[syms]
    act_pnl = r.values @ a_tot
    tot_pnl = r.values @ (b + a_tot)

    def var_es(x, q):
        v = np.quantile(x, 1 - q)
        return float(-v), float(-x[x <= v].mean())

    av95, ae95 = var_es(act_pnl, 0.95)
    tv99, te99 = var_es(tot_pnl, 0.99)
    # VaR backtest: exceptions of the 99% 1-day total VaR (rolling 500-day window) over the last 250 days
    exc = 0
    if len(tot_pnl) > 750:
        for i in range(len(tot_pnl) - 250, len(tot_pnl)):
            exc += int(tot_pnl[i] < np.quantile(tot_pnl[i - 500:i], 0.01))

    by_symbol = sorted(
        [{"symbol": s, "active_pct": round(float(a_tot[i]) * 100, 3),
          "contribution_pct": round(float(contrib[i] / te_after) * 100, 1) if te_after else 0.0} for i, s in enumerate(syms) if abs(a_tot[i]) > 1e-9],
        key=lambda d: -abs(d["contribution_pct"]))
    corr_with_existing = None
    if te_before > 0 and te_alone > 0:
        corr_with_existing = round(float(a_new @ S @ a_old / (te_alone * te_before)), 3)

    out = {
        "te_bp": {"before": round(te_before * 1e4, 1), "after": round(te_after * 1e4, 1), "idea": round(te_alone * 1e4, 1)},
        "budget_bp": reserve.ACTIVE_RISK_BUDGET_BP,
        "budget_used_pct": {"before": round(te_before / budget * 100, 1), "after": round(te_after / budget * 100, 1)},
        "contributions": by_symbol,
        "corr_with_existing": corr_with_existing,
        "active_var95_1d_bp": round(av95 * 1e4, 1), "active_es95_1d_bp": round(ae95 * 1e4, 1),
        "total_var99_1d_pct": round(tv99 * 100, 3), "total_es99_1d_pct": round(te99 * 100, 3),
        "var_backtest": {"exceptions_250d": exc, "expected": 2.5, "limit": 4},
        "notional_usd_bn": reserve.NOTIONAL_USD_BN,
        "active_var95_usd_mn": round(av95 * reserve.NOTIONAL_USD_BN * 1e3, 1),
        "missing_history": missing,
        "data": info,
    }
    out["run_id"] = registry.record("risk", {"active": active, "existing": existing}, {
        "te_after_bp": out["te_bp"]["after"], "budget_used_pct": out["budget_used_pct"]["after"],
        "var_exceptions": exc}, subject, info["end"])
    return out


def max_size_within_budget(tilt: dict[str, float], existing_active: dict[str, float] | None = None,
                           funding: str = "equity", headroom: float = 1.0) -> float:
    """Largest multiple of the tilt that keeps total TE within `headroom` x budget (bisection)."""
    existing = existing_active or {}
    bench = reserve.benchmark_weights()
    syms = sorted(set(bench) | set(tilt) | set(existing) | set(reserve.equity_sleeve()))
    cov, _ = covariance(syms)
    s_ = list(cov.index)
    S = cov.values
    old = np.array([existing.get(s, 0.0) for s in s_])
    unit = active_from_tilt(tilt, funding)
    u = np.array([unit.get(s, 0.0) for s in s_])
    limit = reserve.ACTIVE_RISK_BUDGET_BP / 1e4 * headroom
    if np.sqrt(old @ S @ old) >= limit:
        return 0.0
    lo, hi = 0.0, 1.0
    while np.sqrt((old + hi * u) @ S @ (old + hi * u)) < limit and hi < 64:
        hi *= 2
    for _ in range(40):
        mid = (lo + hi) / 2
        if np.sqrt((old + mid * u) @ S @ (old + mid * u)) < limit:
            lo = mid
        else:
            hi = mid
    return lo


@functools.lru_cache(maxsize=4)
def _factor_frame(key: float) -> pd.DataFrame:
    cols = {}
    for name, (src, sid, how) in FACTORS.items():
        s = store.read_series(src, sid).set_index("date")
        s = s["adjclose"] if "adjclose" in s else s["value"]
        cols[name] = s.pct_change(fill_method=None) if how == "pct" else s.diff()
    return pd.DataFrame(cols)


def macro_betas(symbols: list[str], lookback: int = LOOKBACK) -> dict[str, dict]:
    """OLS betas of daily returns on daily factor moves, scaled to the unit moves in FACTOR_UNIT_MOVE (% return)."""
    f = _factor_frame(_cache_key())
    r = returns(symbols, lookback)
    out = {}
    for s in symbols:
        if s not in r:
            continue
        d = pd.concat([r[s].rename("y"), f], axis=1, join="inner").dropna()
        if len(d) < 120:
            continue
        X = np.column_stack([np.ones(len(d)), d[list(FACTORS)].values])
        coef, *_ = np.linalg.lstsq(X, d["y"].values, rcond=None)
        resid = d["y"].values - X @ coef
        r2 = 1 - resid.var() / d["y"].values.var()
        out[s] = {"betas_pct": {k: round(float(coef[i + 1] * FACTOR_UNIT_MOVE[k] * 100), 2)
                                for i, k in enumerate(FACTORS)},
                  "r2": round(float(r2), 3), "days": len(d)}
    return out


def price_stats(symbol: str) -> dict:
    """Return, volatility, drawdown and liquidity facts for research notes."""
    df = store.read_series("yahoo", symbol)
    px = df.set_index("date")["adjclose"].dropna()
    r = px.pct_change().dropna()
    last = px.index[-1]

    def ret(days):
        return round(float(px.iloc[-1] / px.iloc[-days - 1] - 1) * 100, 1) if len(px) > days else None

    peak = px.iloc[-252:].cummax()
    dd = float((px.iloc[-252:] / peak - 1).min()) * 100
    vol = df.set_index("date")
    ccy = store.catalog_meta(symbol).get("currency")
    fx = 1 / 3.6725 if ccy == "AED" else 1.0  # the dirham is pegged to the dollar at 3.6725
    dollar_vol = float((vol["close"] * vol["volume"]).iloc[-20:].mean()) * fx
    return {"symbol": symbol, "last_date": str(last.date()), "last_price": round(float(px.iloc[-1]), 2),
            "return_1m_pct": ret(21), "return_3m_pct": ret(63), "return_1y_pct": ret(252),
            "return_3y_pct": ret(756), "vol_1y_pct": round(float(r.iloc[-252:].std() * np.sqrt(252) * 100), 1),
            "max_drawdown_1y_pct": round(dd, 1), "avg_daily_value_traded_usd_mn": round(dollar_vol / 1e6, 1),
            "currency": ccy}

