"""Overview: the market snapshot's arithmetic and the curated news feed."""

import time

import pandas as pd
import pytest

from app.core import config, db
from app.data import markets, store
from app.data.connectors import gkg


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    store._ready = gkg._ready = False
    yield
    db._conn = None
    config.get_settings.cache_clear()


def _prices(symbol: str, closes: list[float], end: str = "2026-11-16", meta: dict | None = None):
    dates = pd.bdate_range(end=end, periods=len(closes))
    store.write_series("markets", symbol, pd.DataFrame({"date": dates, "close": closes}), kind="price",
                       title=symbol, meta=meta or {"currency": "USD"})


def test_day_change_in_percent_and_yields_in_basis_points():
    _prices("^GSPC", [100.0] * 30 + [102.0, 99.96])
    _prices("^TNX", [4.0] * 30 + [4.10, 4.067])
    spx = markets.market("^GSPC", "S&P 500", "Global equities", "index")
    tnx = markets.market("^TNX", "US 10-year yield", "Rates", "yield")
    assert spx["day"] == {"pct": -2.0} and spx["month"] == {"pct": -0.04}
    assert tnx["day"] == {"bp": -3.3}
    assert len(spx["spark"]) >= 5


def test_index_without_history_uses_the_quotes_previous_close():
    _prices("DFMGI.AE", [6212.27], meta={"currency": "AED", "chartPreviousClose": 6197.88})
    m = markets.market("DFMGI.AE", "DFM General", "UAE and Gulf", "index")
    assert m["day"] == {"pct": 0.23} and m["month"] is None and m["ytd"] is None and m["spark"] == []


def test_missing_market_is_marked_not_raised():
    assert markets.market("NOPE", "Nothing", "Risk", "index")["missing"] is True


def test_news_feed_keeps_on_topic_original_stories_only():
    gkg._init()
    now = time.time()
    rows = [
        ("https://a.com/1", "oil", now - 60, "Brent crude falls as OPEC signals more supply", "a.com"),
        ("https://b.com/2", "oil", now - 120, "Brent crude falls as OPEC signals more supply, traders say", "b.com"),  # same story
        ("https://c.com/3", "oil", now - 180, "North Atlantic right whale decline alarms scientists", "c.com"),  # off topic
        ("https://prnewswire.com/4", "oil", now - 240, "Company announces oil field services expansion", "prnewswire.com"),
        ("https://d.com/5", "gold", now - 300, "Gold climbs as the dollar slips", "d.com"),
        ("https://e.com/6", "gold", now - 5 * 86400, "Gold hits record", "e.com"),  # older than three days
    ]
    db.conn().executemany("INSERT INTO news_items VALUES(?,?,?,?,?,0,'eng')", rows)
    assert [a["url"] for a in gkg.curated()] == ["https://a.com/1", "https://d.com/5"]
    assert [a["url"] for a in gkg.curated("gold")] == ["https://d.com/5"]
