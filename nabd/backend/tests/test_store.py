import time

import pandas as pd
import pytest

from app.core import config, db
from app.data import store


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    store._ready = False
    yield
    db._conn = None
    config.get_settings.cache_clear()


def frame(dates, values):
    return pd.DataFrame({"date": pd.to_datetime(dates), "value": values})


def test_merge_keeps_first_seen_and_counts_revisions():
    out = store.write_series("t", "s", frame(["2026-01-01", "2026-01-02"], [1.0, 2.0]), kind="macro")
    assert out["added"] == 2
    t0 = time.time()
    time.sleep(0.01)
    out = store.write_series("t", "s", frame(["2026-01-02", "2026-01-03"], [2.5, 3.0]), kind="macro")
    assert out == {**out, "added": 1, "revised": 1, "rows": 3, "last_obs": "2026-01-03"}
    df = store.read_series("t", "s")
    assert df["value"].tolist() == [1.0, 2.5, 3.0]
    # as-of view: only the first two observations were known at t0
    assert len(store.read_series("t", "s", as_of=t0)) == 2


def test_freshness_uses_business_day_lag():
    today = pd.Timestamp.now().normalize()
    old = (today - pd.offsets.BDay(6)).strftime("%Y-%m-%d")
    store.write_series("t", "weekly", frame([old], [1.0]), kind="macro", meta={"max_lag_bd": 8})
    store.write_series("t", "daily", frame([old], [1.0]), kind="macro")
    by_id = {r["id"]: r["freshness"] for r in store.catalog()}
    assert by_id == {"weekly": "fresh", "daily": "late"}


def test_error_marks_series():
    store.mark_error("t", "bad", "price", "symbol not found")
    row = store.catalog()[0]
    assert row["freshness"] == "error" and row["error"] == "symbol not found"
