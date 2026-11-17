import pandas as pd

from app.data.connectors import gkg


def row(title, url="https://x.com/a", themes="", locs="", orgs="", names="", tone="-2.5,1,3"):
    r = [""] * 27
    r[gkg.COLS["url"]], r[gkg.COLS["themes"]], r[gkg.COLS["locations"]] = url, themes, locs
    r[gkg.COLS["orgs"]], r[gkg.COLS["names"]], r[gkg.COLS["tone"]] = orgs, names, tone
    r[gkg.COLS["source"]] = "x.com"
    r[gkg.COLS["extras"]] = f"<PAGE_TITLE>{title}</PAGE_TITLE>"
    return r


def test_theme_matching_and_generic_titles():
    df = pd.DataFrame([
        row("Iran warns tankers near the Strait of Hormuz after naval incident"),
        row("Fed officials signal patience on interest rate cuts this winter", orgs="federal reserve"),
        row("Dubai property and tourism lift UAE growth forecast for next year",
            themes="ECON_GROWTH;", locs="1#Dubai, United Arab Emirates#AE#AE03#25#55#1"),
        row("Latest Articles", themes="ECON_OILPRICE;"),
        row("Local football club wins regional cup in dramatic final match"),
        row("Ethiopia and Sudan accuse each other of backing armed fighters in the region",
            themes="ECON_TRADE;", locs="1#United Arab Emirates#AE#AE#24#54#AE"),
    ])
    aggs, items = gkg.analyse(df, 1794819600, "eng")
    matched = {a["theme"]: a["matched"] for a in aggs}
    assert matched["hormuz"] == 1 and matched["fed_rates"] == 1 and matched["uae_economy"] == 1
    assert matched["oil"] == 1  # counted for volume ...
    assert all(i["title"] != "Latest Articles" for i in items)  # ... but a generic title is not kept as a headline
    assert all(a["total"] == 6 for a in aggs)  # the Ethiopia story mentions the UAE but is not about it
    hormuz = next(a for a in aggs if a["theme"] == "hormuz")
    assert hormuz["tone_sum"] == -2.5
