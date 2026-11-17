"""What to look at: the LLM proposes, Nabd keeps only real instruments and checks every suggestion against data."""

import pytest
from fastapi.testclient import TestClient

from app.core import config, db
from app.invest import ideas, screening
from app.monitoring import alerts


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    ideas._ready = alerts._ready = False
    yield
    db._conn = None
    config.get_settings.cache_clear()


def test_invented_and_duplicate_symbols_never_reach_the_screen():
    p = screening.clean_proposal({
        "driver_label": "AI stocks", "driver_symbols": ["NVDA", "AVGO", "MADEUP", "nvda"],
        "candidates": [{"symbol": "NVDA", "action": "study", "reason": "x"}, {"symbol": "NVDA", "action": "buy", "reason": "dup"},
                       {"symbol": "FAKE1", "action": "protect", "reason": "invented"}, {"symbol": "tlt", "action": "protect", "reason": "y"},
                       {"symbol": "GLD", "action": "sell everything", "reason": "bad action"}]})
    assert p["driver_symbols"] == ["NVDA", "AVGO"]
    assert [(c["symbol"], c["action"]) for c in p["candidates"]] == [("NVDA", "study"), ("TLT", "protect")]


def test_driver_falls_back_to_what_the_idea_is_about():
    p = screening.clean_proposal({"driver_symbols": ["NOPE"], "candidates": [
        {"symbol": "XLE", "action": "buy", "reason": ""}, {"symbol": "XOM", "action": "study", "reason": ""},
        {"symbol": "TLT", "action": "protect", "reason": ""}]})
    assert p["driver_symbols"] == ["XLE", "XOM"]


@pytest.mark.parametrize("action,bearish,beta,worst,agrees", [
    ("hold_less", True, 0.5, -2.0, True), ("hold_less", True, 0.1, -0.2, False),   # must fall with the driver
    ("protect", True, -0.1, 0.3, True), ("protect", True, 0.2, -0.7, False),       # must hold up on its worst days
    ("buy", False, 0.9, -3.0, True), ("buy", False, 0.1, 0.0, False),              # bullish buy must rise with it
    ("study", True, 1.4, -5.0, None),                                              # nothing to check
])
def test_data_check(action, bearish, beta, worst, agrees):
    assert screening._check(action, bearish, beta, worst, "AI stocks")["agrees"] is agrees


def test_screen_starts_a_proposal_for_older_ideas(monkeypatch):
    from app.invest import flow
    from app.main import app
    monkeypatch.setattr(flow, "start_propose", lambda idea_id: "propose-test")
    idea = ideas.create("AI capex slows", "tactical", "test")
    ideas.update(idea["id"], "test", "thesis parsed", thesis={"direction": "underweight", "themes": ["ai"]})
    r = TestClient(app).get(f"/api/invest/ideas/{idea['id']}/screen")
    assert r.status_code == 200 and r.json() == {"status": "proposing", "job_id": "propose-test"}
