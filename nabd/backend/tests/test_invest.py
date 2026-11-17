import numpy as np
import pandas as pd
import pytest

from app.core import config, db
from app.data import store
from app.data.universe import BY_SYMBOL
from app.invest import ideas, screening
from app.ml import registry
from app.ml.portfolio import reserve, risk


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    store._ready = ideas._ready = registry._ready = False
    risk._cov_cached.cache_clear()
    yield
    db._conn = None
    config.get_settings.cache_clear()


def test_benchmark_sums_to_one_and_gold_matches_published_share():
    w = reserve.benchmark_weights()
    assert abs(sum(w.values()) - 1) < 1e-9
    assert 0.03 <= w["GLD"] <= 0.05  # AED 37.9 bn of USD 285 bn is about 3.6%


def test_tilt_is_funded_so_active_weights_net_to_zero():
    a = risk.active_from_tilt({"XLE": 1.0, "SHEL": 0.5})
    assert abs(sum(a.values())) < 1e-12
    assert a["ESGU"] < 0 and a["ESGD"] < 0


def _fake_prices(symbols, n=900, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-02", periods=n)
    common = rng.normal(0, 0.008, n)
    for i, s in enumerate(symbols):
        r = 0.6 * common + rng.normal(0, 0.006 + 0.001 * i, n)
        px = 100 * np.cumprod(1 + r)
        store.write_series("yahoo", s, pd.DataFrame({"date": dates, "open": px, "high": px, "low": px, "close": px,
                                                     "adjclose": px, "volume": 1e6}), kind="price")


def test_tracking_error_grows_with_size_and_budget_search_hits_the_limit():
    syms = sorted(set(reserve.benchmark_weights()) | {"XLE"})
    _fake_prices(syms)
    small = risk.analyse(risk.active_from_tilt({"XLE": 0.5}))
    big = risk.analyse(risk.active_from_tilt({"XLE": 1.0}))
    assert big["te_bp"]["after"] == pytest.approx(2 * small["te_bp"]["after"], rel=0.01)  # rounded to 0.1 bp
    m = risk.max_size_within_budget({"XLE": 1.0})
    at_max = risk.analyse(risk.active_from_tilt({"XLE": m}))
    assert at_max["te_bp"]["after"] == pytest.approx(reserve.ACTIVE_RISK_BUDGET_BP, rel=1e-3)
    assert registry.get(big["run_id"])["model"] == "risk"


def test_fit_score_rewards_theme_and_penalises_wrong_asset_class():
    thesis = {"themes": ["oil", "energy"], "sectors": ["Energy"], "regions": [], "asset_classes": ["equity"]}
    xle, _ = screening._fit_score(BY_SYMBOL["XLE"], thesis)
    bno, reasons = screening._fit_score(BY_SYMBOL["BNO"], thesis)
    msft, _ = screening._fit_score(BY_SYMBOL["MSFT"], thesis)
    assert xle > bno and xle > msft
    assert any("asset class" in r for r in reasons)


def test_memory_finds_past_decisions_and_events_are_append_only():
    a = ideas.create("Overweight Japanese banks as the Bank of Japan normalises rates", "tactical")
    ideas.remember(a["id"], "decision", "Japanese banks: defer. Liquidity of ADRs too thin at our size.")
    b = ideas.create("Another idea about Japan financials and rates", "tactical")
    hits = ideas.search_memory(b["text"], exclude=b["id"])
    assert hits and hits[0]["idea_id"] == a["id"]
    assert any(h["kind"] == "decision" for h in hits)
    ideas.update(a["id"], "tester", "thesis edited", thesis={"title": "x"})
    assert [e["action"] for e in ideas.events(a["id"])] == ["created", "thesis edited"]


def test_placeholder_title_breaks_on_words():
    t = ideas._short("Japanese banks should benefit as the Bank of Japan keeps normalising rates and net margins widen")
    assert t.endswith("…") and not t.endswith(" …") and len(t) <= 71


def test_reduce_idea_sends_net_proceeds_to_treasury_bills():
    a = risk.active_from_tilt({"ESGU": -1.0, "TLT": 0.4})
    assert a["ESGU"] == -0.01 and a["TLT"] == 0.004
    assert abs(a["SHV"] - 0.006) < 1e-12  # the 0.6% not redeployed sits in T-bills
    assert abs(sum(a.values())) < 1e-12


def test_memory_search_with_a_committee_pack_awaiting_its_decision():
    """A related idea at committee with no decision yet (stored as null) must not break a new idea's thesis."""
    from app.invest import ideas
    old = ideas.create("AI crash", "tactical", "test")
    ideas.update(old["id"], "test", "committee pack prepared", stage="committee", committee={"pack": {}, "decision": None})
    ideas.remember(old["id"], "thesis", "AI-linked equities could crash")
    hits = ideas.search_memory("Semiconductor will crash", exclude="none")
    assert hits and hits[0]["decision"] is None
