"""Quantitative tests for deep research. Each returns a compact, JSON-able result (with chart data where useful).

Every function respects AS_OF: when set (a date string), only data up to that date is used, so a research run can
be repeated as it would have looked on a past date.
"""

from __future__ import annotations

import contextvars

import numpy as np
import pandas as pd

from ..data import store
from ..ml.portfolio import regime, reserve

AS_OF: contextvars.ContextVar[str | None] = contextvars.ContextVar("AS_OF", default=None)

FACTOR_SERIES = {  # name -> (source, id, transform)
    "oil": ("fred", "DCOILBRENTEU", "pct"), "rates": ("fred", "DGS10", "diff"), "dollar": ("fred", "DTWEXBGS", "pct"),
    "vix": ("fred", "VIXCLS", "diff"), "gold": ("yahoo", "GLD", "pct"), "spy": ("yahoo", "SPY", "pct"),
    "yen": ("fred", "DEXJPUS", "pct"),
}
EVENT_SOURCES = {
    "fed_moves": "Fed target-rate changes (DFEDTARU)",
    "ecb_moves": "ECB deposit-rate changes (ECBDFR)",
    "jgb_moves": "Months the Japan 10-year yield moved more than 0.1 points (monthly OECD data; event on the "
                 "first trading day of the month, so timing is approximate)",
    "oil_shocks": "Days Brent moved more than 2.5 standard deviations",
    "vix_spikes": "Days the VIX rose more than 20%",
    "rate_jumps": "Days the US 10-year yield moved more than 2.5 standard deviations",
}


def _cut(df: pd.DataFrame) -> pd.DataFrame:
    a = AS_OF.get()
    return df[df.index <= pd.Timestamp(a)] if a else df


def _series(src: str, sid: str) -> pd.Series:
    df = store.read_series(src, sid).set_index("date")
    col = "adjclose" if "adjclose" in df else "value"
    return _cut(df[[col]])[col].dropna()


def _prices(symbols: list[str]) -> pd.DataFrame:
    px = store.close_panel(sorted(set(symbols))).ffill(limit=3)
    return _cut(px)


def _basket_returns(symbols: list[str], bench: str = "SPY") -> tuple[pd.Series, pd.Series]:
    px = _prices(list(symbols) + [bench])
    r = px.pct_change(fill_method=None)
    return r[symbols].mean(axis=1, skipna=True), r[bench]


def _r(x, d=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), d)


# ---------------------------------------------------------------- events
def _event_dates(source: str, direction: str = "any") -> list[pd.Timestamp]:
    def changes(sid, src="fred"):
        s = _series(src, sid)
        d = s.diff()
        d = d[d != 0].dropna()
        if direction == "up":
            d = d[d > 0]
        elif direction == "down":
            d = d[d < 0]
        return list(d.index)

    if source == "fed_moves":
        return changes("DFEDTARU")
    if source == "ecb_moves":
        return changes("ECBDFR")
    if source == "jgb_moves":
        s = _series("fred", "IRLTLT01JPM156N").diff().dropna()
        s = s[s > 0.1] if direction == "up" else s[s < -0.1] if direction == "down" else s[s.abs() > 0.1]
        return list(s.index)
    spec = {"oil_shocks": ("DCOILBRENTEU", "pct", 2.5), "vix_spikes": ("VIXCLS", "pctabs", 0.20),
            "rate_jumps": ("DGS10", "diff", 2.5)}[source]
    s = _series("fred", spec[0])
    if spec[1] == "pctabs":
        ch = s.pct_change()
        hit = ch[ch > spec[2]]
    else:
        ch = s.pct_change() if spec[1] == "pct" else s.diff()
        z = ch / ch.rolling(250, min_periods=120).std()
        hit = z[(z.abs() > spec[2])]
        if direction == "up":
            hit = hit[hit > 0]
        elif direction == "down":
            hit = hit[hit < 0]
    return list(hit.index)


def event_study(symbols: list[str], events: str, direction: str = "any", dates: list[str] | None = None,
                pre: int = 5, post: int = 20, benchmark: str = "SPY") -> dict:
    """Market-adjusted cumulative returns of an equal-weight basket around events (SPY-adjusted by default)."""
    b, m = _basket_returns(symbols, benchmark)
    ab = (b - m).dropna()
    if events == "dates":
        ev = [pd.Timestamp(d) for d in (dates or [])]
        label = "Dates supplied by the researcher (verify them)"
    else:
        ev = _event_dates(events, direction)
        label = EVENT_SOURCES.get(events, events)
    idx = ab.index
    chosen, last = [], None
    for d in sorted(ev):
        pos = idx.searchsorted(d)
        if pos - pre < 0 or pos + post >= len(idx):
            continue
        if last is not None and pos - last < post:  # no overlapping windows
            continue
        chosen.append(pos)
        last = pos
    if len(chosen) < 3:
        return {"error": f"only {len(chosen)} usable events", "event_source": label}
    paths = np.array([ab.iloc[p - pre:p + post + 1].cumsum().values * 100 for p in chosen])
    paths = paths - paths[:, [pre - 1]] if pre > 0 else paths  # start at zero the day before the event
    mean, se = paths.mean(0), paths.std(0, ddof=1) / np.sqrt(len(paths))
    k5, k20 = pre + min(5, post), pre + post
    return {
        "event_source": label, "events": len(chosen), "benchmark": benchmark, "basket": symbols,
        "event_dates_recent": [str(idx[p].date()) for p in chosen[-8:]],
        "car_pct_day5": _r(mean[k5]), "t_day5": _r(mean[k5] / se[k5] if se[k5] else None),
        "car_pct_end": _r(mean[k20]), "t_end": _r(mean[k20] / se[k20] if se[k20] else None),
        "hit_rate_end": _r((paths[:, k20] > 0).mean(), 3),
        "chart": {"days": list(range(-pre, post + 1)), "mean": [_r(x) for x in mean],
                  "lo": [_r(x) for x in mean - 1.96 * se], "hi": [_r(x) for x in mean + 1.96 * se]},
    }


# ---------------------------------------------------------------- conditional returns
def conditional_returns(symbols: list[str], series: str, change_days: int, op: str, threshold: float,
                        horizon_days: int = 63, benchmark: str = "SPY") -> dict:
    """Forward relative returns of the basket after dates when a condition held, against all dates.
    series: a FRED id, a symbol, or 'regime:stress' (probability). change_days=0 means the level, otherwise the
    change over that many trading days (% for prices and indices, points for rates and probabilities)."""
    px = _prices(list(symbols) + [benchmark])
    rel = px[symbols].mean(axis=1).pct_change(fill_method=None).fillna(0) - px[benchmark].pct_change(
        fill_method=None).fillna(0)
    fwd = (rel[::-1].rolling(horizon_days).sum()[::-1]).shift(-1) * 100
    if series == "regime:stress":
        s = regime.stress_prob_series().reindex(px.index, method="ffill")
        kind = "level"
    else:
        src = store.source_of(series) or "fred"
        s = _series(src, series).reindex(px.index, method="ffill")
        kind = "pct" if (src == "yahoo" or series in ("DCOILBRENTEU", "DTWEXBGS", "DEXJPUS", "DEXUSEU")) else "diff"
    x = s if change_days == 0 else (s.pct_change(change_days, fill_method=None) * 100 if kind == "pct" else s.diff(change_days))
    month_ends = px.groupby(px.index.to_period("M")).tail(1).index
    frame = pd.DataFrame({"x": x, "fwd": fwd}).loc[month_ends].dropna()
    cond = frame["x"] > threshold if op == ">" else frame["x"] < threshold
    hit, rest = frame[cond], frame[~cond]
    if len(hit) < 3:
        return {"error": f"condition held in only {len(hit)} month-ends", "months_tested": len(frame)}
    latest = float(x.dropna().iloc[-1]) if len(x.dropna()) else None
    return {
        "condition": f"{series} {'level' if change_days == 0 else f'{change_days}-day change'} {op} {threshold}",
        "condition_now": _r(latest, 3), "condition_true_now": bool(latest is not None and ((latest > threshold) if op == '>' else (latest < threshold))),
        "horizon_days": horizon_days, "benchmark": benchmark, "months_when_true": len(hit), "months_other": len(rest),
        "mean_rel_pct_when_true": _r(hit["fwd"].mean()), "median_rel_pct_when_true": _r(hit["fwd"].median()),
        "hit_rate_when_true": _r((hit["fwd"] > 0).mean(), 3),
        "mean_rel_pct_other": _r(rest["fwd"].mean()), "hit_rate_other": _r((rest["fwd"] > 0).mean(), 3),
        "dates_when_true_recent": [str(d.date()) for d in hit.index[-6:]],
        "chart": {"labels": ["When true", "Other months"], "values": [_r(hit["fwd"].mean()), _r(rest["fwd"].mean())]},
    }


# ---------------------------------------------------------------- analogs
def analogs(symbols: list[str], k: int = 8, horizon_days: int = 63, benchmark: str = "SPY") -> dict:
    """Months whose macro state most resembled the latest one, and how the basket did afterwards."""
    px = _prices(list(symbols) + [benchmark, "SPY"])
    me = px.groupby(px.index.to_period("M")).tail(1).index
    def lvl(sid):
        return _series("fred", sid).reindex(px.index, method="ffill")
    state = pd.DataFrame({
        "brent_3m": lvl("DCOILBRENTEU").pct_change(63, fill_method=None), "ust10": lvl("DGS10"),
        "ust10_3m": lvl("DGS10").diff(63), "vix": lvl("VIXCLS"), "usd_3m": lvl("DTWEXBGS").pct_change(63, fill_method=None),
        "spy_3m": px["SPY"].pct_change(63, fill_method=None),
        "stress": regime.stress_prob_series().reindex(px.index, method="ffill"),
    }).loc[me].dropna()
    z = (state - state.mean()) / state.std()
    now = z.iloc[-1]
    rel = px[symbols].mean(axis=1).pct_change(fill_method=None).fillna(0) - px[benchmark].pct_change(fill_method=None).fillna(0)
    fwd = (rel[::-1].rolling(horizon_days).sum()[::-1]).shift(-1) * 100
    past = z.iloc[:-6]  # leave a gap so analogs are not the recent past
    dist = np.sqrt(((past - now) ** 2).sum(axis=1)).sort_values()
    rows = []
    for d in dist.index:
        f = fwd.get(d)
        if f is None or np.isnan(f):
            continue
        rows.append({"month": str(d.date())[:7], "distance": _r(dist[d]), "fwd_rel_pct": _r(f)})
        if len(rows) >= k:
            break
    vals = np.array([r["fwd_rel_pct"] for r in rows])
    return {"state_now": {c: _r(state.iloc[-1][c], 3) for c in state.columns}, "as_of": str(state.index[-1].date()),
            "analogs": rows, "mean_fwd_rel_pct": _r(vals.mean()), "hit_rate": _r((vals > 0).mean(), 3),
            "horizon_days": horizon_days, "benchmark": benchmark,
            "unconditional_mean_fwd_rel_pct": _r(fwd.loc[me].dropna().mean())}


# ---------------------------------------------------------------- stability and relative performance
def rolling_beta(symbol: str, factor: str, window: int = 126) -> dict:
    """How stable a sensitivity is: rolling beta of daily returns to a factor, sampled monthly over 5 years."""
    src, sid, how = FACTOR_SERIES[factor]
    f = _series(src, sid)
    f = f.pct_change() if how == "pct" else f.diff()
    y = _series("yahoo", symbol).pct_change()
    d = pd.concat([y.rename("y"), f.rename("f")], axis=1, join="inner").dropna()
    beta = d["y"].rolling(window).cov(d["f"]) / d["f"].rolling(window).var()
    b = beta.dropna()
    b = b.groupby(b.index.to_period("M")).tail(1).iloc[-60:]
    if len(b) < 6:
        return {"error": "not enough history"}
    cur = float(b.iloc[-1])
    return {"symbol": symbol, "factor": factor, "window_days": window, "unit": "% return per 1% factor move" if how == "pct" else "% return per 1-point move",
            "current": _r(cur * (100 if how != "pct" else 1), 3), "min": _r(b.min() * (100 if how != "pct" else 1), 3),
            "max": _r(b.max() * (100 if how != "pct" else 1), 3),
            "same_sign_share": _r((np.sign(b) == np.sign(cur)).mean(), 3),
            "chart": {"months": [str(i)[:7] for i in b.index], "beta": [_r(v * (100 if how != 'pct' else 1), 3) for v in b.values]}}


def relative_performance(symbols: list[str], funding: str = "equity") -> dict:
    """The basket (equal weight) against its funding leg: returns, relative drawdown, tracking volatility, IR."""
    fund = reserve.equity_sleeve() if funding == "equity" else {"SHV": 1.0}
    px = _prices(list(symbols) + list(fund))
    r = px.pct_change(fill_method=None)
    basket = r[symbols].mean(axis=1)
    leg = sum(r[s].fillna(0) * w for s, w in fund.items())
    rel = (basket - leg).dropna()
    cum = (1 + rel).cumprod()
    out = {"funding": fund, "basket": symbols}
    for name, n in (("1m", 21), ("3m", 63), ("1y", 252), ("3y", 756)):
        if len(rel) > n:
            out[f"rel_return_{name}_pct"] = _r((cum.iloc[-1] / cum.iloc[-n - 1] - 1) * 100)
    for name, n in (("1y", 252), ("3y", 756)):
        if len(rel) > n:
            x = rel.iloc[-n:]
            out[f"tracking_vol_{name}_pct"] = _r(x.std() * np.sqrt(252) * 100)
            out[f"information_ratio_{name}"] = _r(x.mean() / x.std() * np.sqrt(252) if x.std() else None)
    dd = cum / cum.cummax() - 1
    out["max_rel_drawdown_3y_pct"] = _r(dd.iloc[-756:].min() * 100)
    s = cum.iloc[-756:]
    s = s.groupby(s.index.to_period("W")).tail(1)
    out["chart"] = {"dates": [str(d.date()) for d in s.index], "rel_index": [_r(v * 100, 2) for v in s.values / s.values[0]]}
    return out


def macro_snapshot(series: str) -> dict:
    """Latest value and changes for a FRED macro series (e.g. IRLTLT01JPM156N, IRSTCB01JPM156N, DGS10)."""
    src = store.source_of(series)
    if not src:
        return {"error": f"unknown series {series}"}
    s = _series(src, series)
    last = s.index[-1]

    def back(days):
        prior = s[s.index <= last - pd.Timedelta(days=days)]
        return _r(float(s.iloc[-1] - prior.iloc[-1]), 3) if len(prior) else None
    title = next((r["title"] for r in store.catalog() if r["id"] == series), series)
    return {"series": series, "title": title, "last_date": str(last.date()),
            "last": _r(float(s.iloc[-1]), 3), "change_3m": back(91), "change_1y": back(365), "change_3y": back(1095),
            "max_10y": _r(float(s.iloc[-2520:].max()), 3), "min_10y": _r(float(s.iloc[-2520:].min()), 3)}
