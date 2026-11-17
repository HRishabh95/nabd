import pytest

from app.core import config, db
from app.monitoring import alerts


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    alerts._ready = False
    yield
    db._conn = None
    config.get_settings.cache_clear()


def test_alert_is_raised_once_while_open_and_resolves():
    assert alerts.raise_alert("data", "fred", "stale", "medium", "1 FRED series is late")
    assert not alerts.raise_alert("data", "fred", "stale", "medium", "1 FRED series is late")  # deduplicated
    assert len(alerts.listing("active")) == 1
    assert alerts.resolve("data", "fred", "stale") == 1
    assert alerts.listing("active") == []
    assert alerts.raise_alert("data", "fred", "stale", "medium", "late again")  # can fire again once resolved


def test_acknowledged_alert_stays_active_but_is_not_raised_again():
    alerts.raise_alert("fraud", "run1", "new_cases", "high", "5 new networks")
    a = alerts.listing("active")[0]
    alerts.ack(a["id"], "Risk")
    after = alerts.listing("active")[0]
    assert after["status"] == "acknowledged" and after["acked_by"] == "Risk"
    assert not alerts.raise_alert("fraud", "run1", "new_cases", "high", "5 new networks")
    assert alerts.counts() == {}  # counts are open alerts only


def test_high_severity_sorts_first():
    alerts.raise_alert("forecasting", "q", "contraction", "medium", "contraction")
    alerts.raise_alert("fraud", "r", "new_cases", "high", "networks")
    assert [a["severity"] for a in alerts.listing("active")] == ["high", "medium"]
