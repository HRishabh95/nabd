"""HTTP-level checks: validation, not-found and conflict paths return clear errors, never a 500.

The app is used without its lifespan (no scheduler, monitor or Codex), against an empty temporary data folder.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import ask
from app.core import config, db
from app.data import store
from app.data.connectors import docs, gkg
from app.invest import ideas
from app.jobs import runner
from app.ml import registry
from app.monitoring import alerts

LAZY = (ask, store, docs, gkg, ideas, runner, registry, alerts)  # modules that create their tables on first use


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    for m in LAZY:
        m._ready = False
    yield
    db._conn = None
    config.get_settings.cache_clear()


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def idea(monkeypatch):
    from app.invest import screening
    monkeypatch.setattr(screening, "holdings", lambda: [{"symbol": "DBC", "weight_pct": 3.0}])
    return ideas.create("AI capex slows and semis fall", "tactical", "test")


def test_health(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.parametrize("body", [{"text": "AI", "horizon": "tactical"},          # too short
                                  {"text": "AI crash", "horizon": "forever"},     # unknown horizon
                                  {"text": "x" * 2001, "horizon": "strategic"}])  # too long
def test_new_idea_validation(client, body):
    assert client.post("/api/invest/ideas", json=body).status_code == 422


def test_unknown_idea_is_404(client):
    assert client.get("/api/invest/ideas/nope").status_code == 404
    assert client.delete("/api/invest/ideas/nope").status_code == 404


def test_screen_before_thesis_is_409(client, idea):
    assert client.get(f"/api/invest/ideas/{idea['id']}/screen").status_code == 409


@pytest.mark.parametrize("items,msg", [
    ([{"symbol": "NOT_A_TICKER'; DROP TABLE x;--", "weight_pct": 1}], "Not in the universe"),
    ([{"symbol": "NVDA", "weight_pct": 1}], "Not investable"),  # equities can be researched, never traded
    ([{"symbol": "GLD", "weight_pct": -1}, {"symbol": "GLD", "weight_pct": -0.5}], "appear once"),
    ([{"symbol": "GLD", "weight_pct": 0}], "cannot be zero"),
    ([{"symbol": "DBC", "weight_pct": -4}], "can cut at most 3.00%"),
    ([{"symbol": "UNG", "weight_pct": -1}], "can cut at most 0.00%"),  # not held: cannot short
])
def test_basket_validation(client, idea, items, msg):
    r = client.post(f"/api/invest/ideas/{idea['id']}/basket", json={"items": items})
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_basket_schema_bounds(client, idea):
    assert client.post(f"/api/invest/ideas/{idea['id']}/basket", json={"items": []}).status_code == 422
    big = {"items": [{"symbol": "NVDA", "weight_pct": 11}]}
    assert client.post(f"/api/invest/ideas/{idea['id']}/basket", json=big).status_code == 422


def test_later_stages_refuse_out_of_order(client, idea):
    i = idea["id"]
    assert client.post(f"/api/invest/ideas/{i}/research", json={}).status_code == 409
    assert client.post(f"/api/invest/ideas/{i}/fit").status_code == 409
    assert client.post(f"/api/invest/ideas/{i}/committee").status_code == 409
    assert client.post(f"/api/invest/ideas/{i}/decision", json={"decision": "approve", "rationale": "x"}).status_code == 409
    assert client.post(f"/api/invest/ideas/{i}/decision", json={"decision": "maybe"}).status_code == 422


def test_delete_idea_is_soft_and_once(client, idea):
    i = idea["id"]
    assert client.delete(f"/api/invest/ideas/{i}").status_code == 200
    assert i not in [x["id"] for x in client.get("/api/invest/ideas").json()["ideas"]]
    assert client.delete(f"/api/invest/ideas/{i}").status_code == 409


def test_modules_without_runs_say_so(client):
    assert client.get("/api/fraud").status_code == 404
    assert client.get("/api/fraud/case/combined/C001").status_code == 404
    assert client.get("/api/forecast").status_code == 404
    assert client.get("/api/data/series/not-a-series").status_code == 404
    assert client.post("/api/data/refresh/not-a-source").status_code == 404
    assert client.get("/api/ask/threads/nope").status_code == 404


def test_monitor_endpoints_on_empty_data(client):
    alerts.raise_alert("data", "fred", "stale", "medium", "1 FRED series is late")
    r = client.get("/api/monitor/alerts")
    assert r.status_code == 200 and len(r.json()["alerts"]) == 1
    a = r.json()["alerts"][0]
    assert client.post(f"/api/monitor/alerts/{a['id']}/ack").status_code == 200
    assert client.get("/api/monitor/alerts").json()["alerts"][0]["acked_by"] == "Investment team"
    audit = client.get("/api/monitor/audit").json()["events"]
    assert any(e["action"].startswith("Acknowledged") for e in audit)
