import asyncio
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.core import config
from app.ml.forecasting import ai_news, data, kalman


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    ai_news._ready = False
    yield
    config.get_settings.cache_clear()
    ai_news._ready = False


def synthetic(monkeypatch, news: bool = False, seed: int = 0):
    """A monthly panel driven by one factor, and GDP = 4 + 1.5 * quarterly factor + noise."""
    rng = np.random.default_rng(seed)
    idx = pd.period_range("2020-01", "2026-06", freq="M")
    f = np.zeros(len(idx))
    for t in range(1, len(idx)):
        f[t] = 0.8 * f[t - 1] + rng.normal()
    cols = {c: 10 * (0.9 * f + 0.4 * rng.normal(size=len(idx))) for c in kalman.HARD}
    if news:
        cols["ai_nonoil"] = 0.5 * f + 0.3 * rng.normal(size=len(idx))
    pm = pd.DataFrame(cols, index=idx)
    fq = pd.Series(f, index=idx).groupby(idx.asfreq("Q")).mean()
    gdp = 4 + 1.5 * fq + 0.2 * rng.normal(size=len(fq))

    def target(name, as_of=None, training=False):
        out = gdp.copy()
        if as_of is not None:  # released 60 days after the quarter ends
            out = out[[(q + 1).asfreq("D", "start").to_timestamp() + pd.Timedelta(days=60) <= as_of for q in out.index]]
        return out

    monkeypatch.setattr(data, "target", target)
    return pm, gdp


def test_nowcast_tracks_gdp_and_handles_the_ragged_edge(monkeypatch):
    pm, gdp = synthetic(monkeypatch)
    q = pd.Period("2026Q1", "Q")
    as_of = pd.Timestamp("2026-02-15")
    ragged = pm.copy()
    ragged.loc[pd.Period("2026-02", "M"):, :] = np.nan        # February onwards not yet published
    ragged.loc[pd.Period("2026-01", "M"), ["emaar", "enbd"]] = np.nan  # two series a month behind
    o = kalman.nowcast("non_oil", q, as_of, "kalman", ragged)
    assert o is not None and o["detail"]["beta"][0] > 0
    assert abs(o["value"] - gdp[q]) < 2.5 * o["sd"]
    full = kalman.nowcast("non_oil", q, pd.Timestamp("2026-04-15"), "kalman", pm)
    assert full["sd"] < o["sd"]  # more data, less uncertainty


def test_contributions_add_up_to_the_nowcast(monkeypatch):
    pm, _ = synthetic(monkeypatch)
    q, as_of = pd.Period("2026Q2", "Q"), pd.Timestamp("2026-05-10")
    pm = pm.loc[: pd.Period("2026-04", "M")]
    m = kalman.fit("non_oil", q, as_of, "kalman", pm)
    v, _ = kalman.predict(m, q)
    c = kalman.contributions(m, q)
    assert set(c) == set(m.names) | {"gdp"}
    assert m.mu + sum(c.values()) == pytest.approx(v, abs=1e-8)


def test_revision_breakdown_is_exact(monkeypatch):
    pm, _ = synthetic(monkeypatch)
    q = pd.Period("2026Q2", "Q")
    a, b = pd.Timestamp("2026-04-20"), pd.Timestamp("2026-06-20")
    r = kalman.revision("non_oil", q, a, b, "kalman", pm.loc[: pd.Period("2026-03", "M")],
                        pm.loc[: pd.Period("2026-05", "M")])
    assert r["from"] + sum(s["change"] for s in r["steps"]) == pytest.approx(r["to"], abs=1e-8)
    assert r["steps"][0]["input"] == "reestimation"


def test_news_variant_needs_its_series_and_adds_a_factor(monkeypatch):
    pm, _ = synthetic(monkeypatch, news=True)
    q, as_of = pd.Period("2026Q1", "Q"), pd.Timestamp("2026-04-10")
    assert kalman.nowcast("non_oil", q, as_of, "kalman_ai", pm.drop(columns="ai_nonoil")) is None
    o = kalman.nowcast("non_oil", q, as_of, "kalman_ai", pm)
    assert o["detail"]["factors"] == 2 and "ai_nonoil" in o["detail"]["inputs"]


def test_gdp_weights_are_never_negative():
    rng = np.random.default_rng(1)
    A = rng.normal(size=(12, 2))
    A = A - A.mean(0)
    A[:, 1] -= A[:, 0] * (A[:, 0] @ A[:, 1]) / (A[:, 0] @ A[:, 0])  # uncorrelated columns
    y = -2 * A[:, 0] + 0.5 * A[:, 1] + 0.1 * rng.normal(size=12)
    b = kalman._signed_ridge(A - A.mean(0), y - y.mean(), 1.0)
    assert b[0] == 0 and b[1] > 0


def _gkg_row(title: str, source: str, locs: str = "", themes: str = "") -> list[str]:
    row = [""] * 27
    row[3], row[4], row[7], row[9] = source, f"https://{source}/a", themes, locs
    row[26] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return row


def test_headline_filter_keeps_uae_business_news_only():
    df = pd.DataFrame([
        _gkg_row("Dubai airport passenger traffic hits record in first half", "reuters.com"),
        _gkg_row("Celebrity spotted on holiday in Dubai again", "tabloid.com"),
        _gkg_row("Saudi Arabia raises crude output in March", "reuters.com"),
        _gkg_row("Developers launch new towers as sales climb", "gulfnews.com", locs="1#Dubai#AE#"),
        _gkg_row("Short", "gulfnews.com", locs="1#Dubai#AE#", themes="ECON_STOCKMARKET"),
    ])
    kept = ai_news.select(df)["title"].tolist()
    assert kept == ["Dubai airport passenger traffic hits record in first half",
                    "Developers launch new towers as sales climb"]


def test_labelling_is_blind_to_dates_and_builds_a_daily_signal(monkeypatch):
    ai_news._init()
    from app.core.db import conn
    jan, feb = pd.Timestamp("2024-01-10").timestamp(), pd.Timestamp("2024-02-12").timestamp()
    rows = [("a", "2024-01", jan, "Dubai port volumes jump to a record", "x", "u1", "eng"),
            ("b", "2024-01", jan, "UAE hotels report weaker bookings", "x", "u2", "eng"),
            ("c", "2024-02", feb, "ADNOC raises crude output capacity", "x", "u3", "eng")]
    conn().executemany("INSERT INTO news_archive VALUES(?,?,?,?,?,?,?)", rows)
    seen = []

    async def fake_run(purpose, rules, prompt, schema=None, timeout_seconds=None):
        seen.append(prompt)
        titles = [ln.split(". ", 1)[1] for ln in prompt.splitlines() if ln[:1].isdigit()]
        lab = {"Dubai port volumes jump to a record": ("trade_logistics", 2),
               "UAE hotels report weaker bookings": ("tourism_aviation", -1),
               "ADNOC raises crude output capacity": ("oil_gas", 1)}
        items = [ai_news.HeadlineLabel(i=k, rel=True, sector=lab[t][0], dir=lab[t][1]) for k, t in enumerate(titles, 1)]
        return SimpleNamespace(parsed=ai_news.Labels(items=items), text="", model="test")

    import app.llm.gateway as gw
    monkeypatch.setattr(gw.gateway, "run", fake_run)
    stats = asyncio.run(ai_news.label())
    assert stats["labelled"] == 3
    assert not any(s in seen[0] for s in ("2024", "Jan", "Feb", "gulfnews", "u1"))  # no dates, sources or links
    ai_news.build_series()
    monkeypatch.setattr(data, "_cache", {})
    no = data.monthly("ai_nonoil")
    # diffusion: 100 * (stronger - weaker) / (relevant + 5): one up, one down in January balances to zero
    assert no[pd.Period("2024-01", "M")] == pytest.approx(0.0)
    assert data.monthly("ai_oil")[pd.Period("2024-02", "M")] == pytest.approx(100 / 6)  # one stronger, shrunk
