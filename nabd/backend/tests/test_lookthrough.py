"""Look-through: the mandates' holdings make single-name underweights possible without ever going short."""

import pytest
from fastapi.testclient import TestClient

from app.core import config, db
from app.invest import ideas, lookthrough
from app.ml.portfolio import reserve, risk
from app.monitoring import alerts

SAMPLE = '''iShares ESG Aware MSCI USA ETF
Fund Holdings as of,"Nov 14, 2026"
Inception Date,"Dec 01, 2016"
\xa0
Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date
"NVDA","NVIDIA CORP","Information Technology","Equity","1,000","7.50","1,000","10","100","United States","NASDAQ","USD","1.00","USD","-"
"MSFT","MICROSOFT CORP","Information Technology","Equity","900","6.00","900","9","100","United States","NASDAQ","USD","1.00","USD","-"
"XYZ","SOMETHING NOT IN THE UNIVERSE INC","Industrials","Equity","10","0.10","10","1","10","United States","NYSE","USD","1.00","USD","-"
"USD","USD CASH","Cash and/or Derivatives","Cash","5","0.05","5","5","1","United States","-","USD","1.00","USD","-"
\xa0
"The content contained herein is owned or licensed by BlackRock"
'''


@pytest.fixture(autouse=True)
def tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    db._conn = None
    ideas._ready = alerts._ready = False
    yield tmp_path
    db._conn = None
    config.get_settings.cache_clear()


def test_parse_ishares_file():
    hold, as_of = lookthrough.parse_ishares(SAMPLE)
    assert as_of == "Nov 14, 2026"
    assert hold["NVDA"]["weight"] == pytest.approx(0.075) and "USD" not in hold  # cash lines are not companies


def test_match_by_ticker_and_by_name():
    hold = {"NVDA": {"name": "NVIDIA CORP", "weight": 0.07}, "8306": {"name": "MITSUBISHI UFJ FINANCIAL GROUP INC", "weight": 0.01}}
    got = lookthrough._match(hold)
    assert got["NVDA"] == 0.07
    assert got.get("MUFG") == 0.01  # a Tokyo line found by company name


def test_indirect_weight_and_missing_files(tmp_data):
    assert lookthrough.load()["ESGU"]["loaded"] is False
    (tmp_data / "manual").mkdir()
    (tmp_data / "manual" / "ESGU_holdings.csv").write_text(SAMPLE)
    lt = lookthrough.load()
    assert lt["ESGU"]["loaded"] and lt["ESGU"]["holdings"] == 3
    via = lookthrough.indirect({"ESGU": 7.0}, lt)
    assert via["NVDA"] == pytest.approx(0.525)  # 7% of the portfolio in the mandate × 7.5% of the mandate


def test_basket_underweight_capped_by_lookthrough(tmp_data, monkeypatch):
    from app.invest import screening
    from app.main import app
    monkeypatch.setattr(screening, "holdings", lambda: [{"symbol": "ESGU", "weight_pct": 7.0}])
    (tmp_data / "manual").mkdir()
    (tmp_data / "manual" / "ESGU_holdings.csv").write_text(SAMPLE)
    idea = ideas.create("AI capex slows and semis fall", "tactical", "test")
    c = TestClient(app, raise_server_exceptions=False)
    url = f"/api/invest/ideas/{idea['id']}/basket"
    too_far = c.post(url, json={"items": [{"symbol": "NVDA", "weight_pct": -0.6}]})
    assert too_far.status_code == 422 and "0.53%" in too_far.json()["detail"] and "through the mandates" in too_far.json()["detail"]
    zero = c.post(url, json={"items": [{"symbol": "NVDA", "weight_pct": 0}]})
    assert zero.status_code == 422 and "research only" in zero.json()["detail"]
    from app.invest import flow
    monkeypatch.setattr(flow, "start_research", lambda *a, **k: "job-test")
    ok = c.post(url, json={"items": [{"symbol": "NVDA", "weight_pct": -0.4}, {"symbol": "AVGO", "research_only": True}],
                           "funding": "mandate"})
    assert ok.status_code == 200, ok.text
    basket = ok.json()["idea"]["basket"]
    assert flow.trade_lines(basket) == {"NVDA": -0.4}  # the research-only name never reaches the risk model
    assert [b["research_only"] for b in basket["items"]] == [False, True]


def test_research_only_basket_cannot_go_to_fit(monkeypatch):
    from app.invest import flow
    from app.main import app
    idea = ideas.create("Study AI names first", "tactical", "test")
    flow.set_basket(idea["id"], [{"symbol": "NVDA", "weight_pct": 0, "research_only": True}], "cash", "test")
    r = TestClient(app, raise_server_exceptions=False).post(f"/api/invest/ideas/{idea['id']}/fit")
    assert r.status_code == 409 and "research only" in r.json()["detail"]


def test_cut_proceeds_can_stay_in_the_mandates():
    to_bills = risk.active_from_tilt({"NVDA": -0.5}, "cash")
    assert to_bills == {"NVDA": -0.005, "SHV": pytest.approx(0.005)}
    in_equity = risk.active_from_tilt({"NVDA": -0.5}, "mandate")
    sleeve = reserve.equity_sleeve()
    assert "SHV" not in in_equity and sum(in_equity.values()) == pytest.approx(0)
    assert in_equity["ESGU"] == pytest.approx(0.005 * sleeve["ESGU"])
