"""Target and indicators for the UAE GDP nowcast, with real-time discipline.

Target: FCSC quarterly real GDP growth and non-oil real GDP growth, year on year, AS FIRST RELEASED, from the
release record in data/manual/fcsc_quarterly_gdp.csv (each value with its release date and official source).
FCSC blocks automated access, so the record is compiled from official releases (FCSC, WAM) and can be replaced
by an analyst's download of the full FCSC series.

Indicators (monthly, year-on-year): Hormuz transits and UAE port calls (IMF PortWatch), Brent (FRED), UAE equities
(MSCI UAE ETF, Emaar, Emirates NBD), VIX, US 10-year yield, broad dollar, and GDELT news volume and tone on the UAE
economy and Hormuz. Each has a publication lag; `panel(as_of)` returns only what was knowable on that date, with
the current month built from the days available so far (the ragged edge).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from ...core.config import get_settings
from ...data import store

TARGETS = {"non_oil": "Non-oil real GDP growth, % y/y", "real": "Real GDP growth, % y/y"}

# name: (source, series, column, monthly aggregation, transform, publication lag in days, label)
INDICATORS = {
    "hormuz": ("portwatch", "pw:hormuz", "ships", "mean", "logyoy", 5, "Hormuz transits"),
    "ports": ("portwatch", "pw:uae_ports", "portcalls", "mean", "logyoy", 5, "UAE port calls"),
    "imports": ("portwatch", "pw:uae_ports", "imports", "mean", "logyoy", 5, "UAE import volume"),
    "exports": ("portwatch", "pw:uae_ports", "exports", "mean", "logyoy", 5, "UAE export volume"),
    "brent": ("fred", "DCOILBRENTEU", "value", "mean", "logyoy", 7, "Brent crude"),
    "uae_equity": ("yahoo", "UAE", "adjclose", "last", "logyoy", 1, "UAE equities (MSCI UAE)"),
    "emaar": ("yahoo", "EMAAR.AE", "adjclose", "last", "logyoy", 1, "Emaar (property)"),
    "enbd": ("yahoo", "EMIRATESNBD.AE", "adjclose", "last", "logyoy", 1, "Emirates NBD (banks)"),
    "vix": ("fred", "VIXCLS", "value", "mean", "level", 2, "VIX"),
    "ust10": ("fred", "DGS10", "value", "mean", "diffyoy", 2, "US 10-year yield"),
    "dollar": ("fred", "DTWEXBGS", "value", "mean", "logyoy", 8, "Broad dollar"),
    "news_uae_tone": ("gdelt", "news:uae_economy", "tone", "mean", "diffyoy", 1, "News tone: UAE economy"),
    "news_hormuz_vol": ("gdelt", "news:hormuz", "volume", "mean", "level", 1, "News volume: Hormuz"),
}
CORE = ["hormuz", "ports", "brent", "uae_equity", "vix", "news_uae_tone"]  # used by the compact models


SEED = Path(__file__).parent / "seed"


def _manual(name: str) -> Path:
    """data/manual/<name>; on a fresh install the release record shipped with the code is copied in, so an analyst
    can later replace it with the full FCSC series without touching the code."""
    p = get_settings().data_dir / "manual" / name
    if not p.exists() and (SEED / name).exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SEED / name, p)
    return p


def target_record() -> pd.DataFrame:
    p = _manual("fcsc_quarterly_gdp.csv")
    df = pd.read_csv(p)
    df["period"] = pd.PeriodIndex(df["quarter"].str.replace(" ", ""), freq="Q")
    df["release_date"] = pd.to_datetime(df["release_date"], errors="coerce")
    for c in ("real_gdp_yoy", "non_oil_yoy"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("period").reset_index(drop=True)


def later_vintage() -> pd.DataFrame:
    p = _manual("fcsc_quarterly_gdp_later_vintage.csv")
    if not p.exists():
        return pd.DataFrame(columns=["period", "real_gdp_yoy", "non_oil_yoy", "release_date"])
    df = pd.read_csv(p)
    df["period"] = pd.PeriodIndex(df["quarter"], freq="Q")
    df["release_date"] = pd.to_datetime(df["release_date"])
    return df


def target(name: str, as_of: pd.Timestamp | None = None, training: bool = False) -> pd.Series:
    """Quarterly target as first released, keeping only quarters published by `as_of`. With training=True, later-
    vintage values for quarters that never had a first release are added (training only; never scored)."""
    df = target_record()
    if training:
        lv = later_vintage()
        lv = lv[~lv["period"].isin(df.dropna(subset=["real_gdp_yoy"])["period"])]
        df = pd.concat([df.dropna(subset=["release_date"]), lv], ignore_index=True)
    col = "non_oil_yoy" if name == "non_oil" else "real_gdp_yoy"
    if as_of is not None:
        df = df[df["release_date"].notna() & (df["release_date"] <= as_of)]
    s = df.set_index("period")[col].dropna()
    s = s[~s.index.duplicated(keep="first")]
    return s.sort_index()


def _daily(name: str) -> pd.Series:
    src, sid, col, *_ = INDICATORS[name]
    df = store.read_series(src, sid).set_index("date")
    return df[col].dropna().astype(float)


_cache: dict = {}


def _daily_cached(name: str) -> pd.Series:
    key = (name, max((r["last_refresh"] or 0) for r in store.catalog()) if store.catalog() else 0)
    if key not in _cache:
        _cache.clear() if len(_cache) > 64 else None
        _cache[key] = _daily(name)
    return _cache[key]


def monthly(name: str, as_of: pd.Timestamp | None = None) -> pd.Series:
    """Monthly level of an indicator, using only days published by `as_of` (the last month may be partial)."""
    _, _, _, agg, _, lag, _ = INDICATORS[name]
    s = _daily_cached(name)
    if as_of is not None:
        s = s[s.index <= as_of - pd.Timedelta(days=lag)]
    if s.empty:
        return s
    g = s.groupby(s.index.to_period("M"))
    return g.last() if agg == "last" else g.mean()


def transformed(name: str, as_of: pd.Timestamp | None = None) -> pd.Series:
    m = monthly(name, as_of)
    how = INDICATORS[name][4]
    if how == "logyoy":  # percentage change on a year earlier: bounded at -100% when activity collapses
        out = (m / m.shift(12).where(m.shift(12) > 0) - 1) * 100
    elif how == "diffyoy":
        out = m - m.shift(12)
    else:
        out = m
    return out.dropna()


def panel(as_of: pd.Timestamp | None = None, names: list[str] | None = None) -> pd.DataFrame:
    """Monthly indicator panel (transformed), aligned on months; NaN where an indicator has no data yet."""
    cols = {}
    for n in names or list(INDICATORS):
        try:
            t = transformed(n, as_of)
        except FileNotFoundError:
            continue
        if len(t):  # an empty series would turn the month index into plain objects
            cols[n] = t
    pm = pd.DataFrame(cols).sort_index()
    pm.index = pd.PeriodIndex(pm.index, freq="M")
    return pm


def quarterly_features(pm: pd.DataFrame, fill_ragged: bool = True) -> pd.DataFrame:
    """Quarter averages of the monthly panel. For the latest quarter, missing months are filled with the last
    available value of each indicator (a carry-forward ragged-edge rule), and the share of months observed is kept."""
    pm = pm.copy()
    if fill_ragged and len(pm):
        last_q = pm.index[-1].asfreq("Q")
        months = pd.period_range(last_q.asfreq("M", "start"), last_q.asfreq("M", "end"), freq="M")
        idx = pd.PeriodIndex(sorted(set(pm.index) | set(months)), freq="M")
        pm = pm.reindex(idx).ffill(limit=2)
    pm.index = pd.PeriodIndex(pm.index, freq="M")
    q = pm.groupby(pm.index.asfreq("Q")).mean()
    return q


def months_observed(pm: pd.DataFrame, quarter: pd.Period) -> dict[str, int]:
    months = pd.period_range(quarter.asfreq("M", "start"), quarter.asfreq("M", "end"), freq="M")
    return {c: int(pm[c].reindex(months).notna().sum()) for c in pm.columns}


def latest_inputs(as_of: pd.Timestamp | None = None) -> list[dict]:
    out = []
    for n, (src, sid, col, agg, how, lag, label) in INDICATORS.items():
        try:
            m = monthly(n, as_of)
            t = transformed(n, as_of)
        except FileNotFoundError:
            out.append({"name": n, "label": label, "error": "not downloaded"})
            continue
        if m.empty:
            continue
        unit = {"logyoy": "% y/y", "diffyoy": "change y/y", "level": "level"}[how]  # logyoy = % change y/y
        out.append({"name": n, "label": label, "source": src, "series": sid, "unit": unit, "lag_days": lag,
                    "last_month": str(m.index[-1]), "last_level": round(float(m.iloc[-1]), 3),
                    "last_value": round(float(t.iloc[-1]), 2) if len(t) else None,
                    "value_3m_ago": round(float(t.iloc[-4]), 2) if len(t) > 3 else None})
    return out
