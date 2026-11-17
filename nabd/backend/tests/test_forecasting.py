import pandas as pd
import pytest

from app.core import config
from app.ml.forecasting import data


@pytest.fixture(autouse=True)
def manual_files(tmp_path, monkeypatch):
    (tmp_path / "manual").mkdir()
    (tmp_path / "manual" / "fcsc_quarterly_gdp.csv").write_text(
        "quarter,real_gdp_yoy,non_oil_yoy,release_date,source_url,source_type,note\n"
        "2023Q1,3.8,4.5,2023-08-01,u,press_quoting_fcsc,\n"
        "2023Q2,,,,,,no release\n"
        "2023Q3,2.5,5.8,2024-03-29,u,cbuae,\n")
    (tmp_path / "manual" / "fcsc_quarterly_gdp_later_vintage.csv").write_text(
        "quarter,real_gdp_yoy,non_oil_yoy,release_date,source_url,source_type,note\n"
        "2022Q4,5.5,5.2,2023-09-28,u,cbuae,later vintage\n"
        "2023Q2,3.9,7.0,2024-01-15,u,cbuae,later vintage\n")
    monkeypatch.setenv("NABD_DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_target_respects_release_dates():
    assert data.target("non_oil", pd.Timestamp("2023-12-31")).to_dict() == {pd.Period("2023Q1", "Q"): 4.5}
    assert len(data.target("non_oil", pd.Timestamp("2024-04-01"))) == 2


def test_later_vintage_is_for_training_only_and_kept_in_order():
    scored = data.target("non_oil")
    train = data.target("non_oil", training=True)
    assert pd.Period("2022Q4", "Q") not in scored.index and pd.Period("2022Q4", "Q") in train.index
    assert list(train.index) == sorted(train.index)  # the latest release is last, so the benchmark reads it
    # a later vintage only appears once it was published
    early = data.target("non_oil", pd.Timestamp("2023-12-31"), training=True)
    assert pd.Period("2023Q2", "Q") not in early.index


def test_ragged_edge_fills_missing_months_of_the_latest_quarter():
    pm = pd.DataFrame({"ports": [1.0, 2.0, 3.0, 4.0]},
                      index=pd.PeriodIndex(["2026-07", "2026-08", "2026-09", "2026-10"], freq="M"))
    q = data.quarterly_features(pm)
    assert q.loc[pd.Period("2026Q3", "Q"), "ports"] == 2.0
    assert q.loc[pd.Period("2026Q4", "Q"), "ports"] == 4.0  # October carried into November and December
    assert data.months_observed(pm, pd.Period("2026Q4", "Q")) == {"ports": 1}
