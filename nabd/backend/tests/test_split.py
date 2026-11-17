"""Before research: the portfolio split a selection implies. After research: the split it proposes, checked."""

import pytest

from app.core import config, db
from app.invest import deep, flow, ideas, screening
from app.ml.portfolio import risk
from app.monitoring import alerts


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    ideas._ready = alerts._ready = False
    monkeypatch.setattr(screening, "holdings", lambda: [{"symbol": "ESGU", "weight_pct": 7.0, "name": "ESGU"}])
    monkeypatch.setattr(risk, "analyse", lambda active, existing, subject=None: {
        "te_bp": {"after": 10.0}, "budget_used_pct": {"before": 0.0, "after": 16.7}, "budget_bp": 60.0})
    yield
    db._conn = None
    config.get_settings.cache_clear()


def _idea(direction="underweight"):
    i = ideas.create("AI capex slows", "tactical", "test")
    ideas.update(i["id"], "test", "thesis parsed", thesis={"direction": direction})
    return ideas.get(i["id"])


def test_research_only_names_are_tested_at_their_test_size():
    p = flow.preview(_idea(), [{"symbol": "GLD", "research_only": True, "test_pct": 0.5}], "cash")
    assert p["research_only"][0]["symbol"] == "GLD"
    assert p["hypothetical"] == {"GLD": 0.5} and p["risk"] is not None  # fit and stress have something to test
    tested, hypo = flow.tested_lines({"items": [{"symbol": "DBC", "weight_pct": 1.0},
                                                {"symbol": "GLD", "weight_pct": 0, "research_only": True}]})
    assert tested == {"DBC": 1.0, "GLD": flow.TEST_PCT} and hypo == {"GLD": flow.TEST_PCT}


def test_split_by_asset_class_moves_with_the_trade():
    p = flow.preview(_idea(), [{"symbol": "GLD", "weight_pct": 0.5}], "cash")
    by = {c["name"]: c for c in p["by_class"]}
    assert by["Gold"]["after_pct"] - by["Gold"]["before_pct"] == pytest.approx(0.5)
    assert by["Cash and T-bills"]["after_pct"] - by["Cash and T-bills"]["before_pct"] == pytest.approx(-0.5)
    assert by["Commodities"]["after_pct"] == pytest.approx(by["Commodities"]["before_pct"])  # gold does not touch commodities
    assert p["risk"]["budget_used_after_pct"] == 16.7


def test_check_split_enforces_limits(monkeypatch):
    idea = _idea()
    flow.set_basket(idea["id"], [{"symbol": "ESGU", "weight_pct": -0.5}, {"symbol": "NVDA", "research_only": True}], "cash", "test")
    monkeypatch.setattr(flow, "preview", lambda idea, items, funding: {"items": items})
    out = deep.check_split(ideas.get(idea["id"]), [
        {"symbol": "ESGU", "weight_pct": -9.0, "why": "too big"},       # more than the 7% held
        {"symbol": "NVDA", "weight_pct": 0.0, "why": "evidence weak"},   # left out: stays research only
        {"symbol": "TSLA", "weight_pct": 0.3, "why": "not selected"}])   # not in the selection
    assert [(x["symbol"], x["weight_pct"]) for x in out["lines"]] == [("ESGU", -7.0), ("NVDA", 0.0)]
    assert any("capped at 7.00%" in n for n in out["notes"]) and any("TSLA" in n for n in out["notes"])
    assert out["check"]["items"] == [{"symbol": "ESGU", "weight_pct": -7.0}, {"symbol": "NVDA", "research_only": True}]


def test_sri_warning_applies_to_equities_only():
    from app.data.universe import BY_SYMBOL
    tilt = {"GLD": 0.5, "XLK": 0.3}
    flagged = [s for s in tilt if BY_SYMBOL[s].asset == "equity" and not BY_SYMBOL[s].sri]
    assert flagged == ["XLK"]  # mirrors flow.compute_fit: gold is outside SRI screening
