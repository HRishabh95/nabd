import numpy as np
import pandas as pd

from app.ml.fraud import detect, generator


def _tx(rows):
    df = pd.DataFrame(rows, columns=["src", "dst", "amount", "minute"])
    df["ts"] = pd.Timestamp("2026-11-02 09:00") + pd.to_timedelta(df.minute, "m")
    df["cross_bank"] = 1
    df["laundering"] = 0
    return df.drop(columns="minute").reset_index(drop=True)


def test_pass_through_needs_matching_money_in_and_out():
    tx = _tx([("A", "M", 50000, 0), ("M", "B", 48000, 30),      # forwarded within the hour: pass-through
              ("C", "N", 50000, 0), ("N", "D", 9000, 30),       # forwards a small part: not a pass-through
              ("E", "O", 50000, 0), ("O", "F", 48000, 600)])    # forwards after 10 hours: outside the window
    fast = detect.pass_through(tx, hold_min=240, flow_min=0.7, min_amount=5000)
    pairs = set(zip(fast.src, fast.dst))
    assert ("M", "B") in pairs and ("A", "M") in pairs
    assert ("N", "D") not in pairs and ("O", "F") not in pairs


def test_split_forwarding_still_counts_as_pass_through():
    tx = _tx([("A", "M", 60000, 0), ("M", "B", 20000, 20), ("M", "C", 20000, 25), ("M", "D", 19000, 30)])
    fast = detect.pass_through(tx, hold_min=240, flow_min=0.7, min_amount=5000)
    assert {("M", "B"), ("M", "C"), ("M", "D")} <= set(zip(fast.src, fast.dst))


def test_cycle_found_whatever_account_the_listing_starts_from():
    t = {("A", "B"): [np.datetime64("2026-11-02T10:00")], ("B", "C"): [np.datetime64("2026-11-02T11:00")],
         ("C", "A"): [np.datetime64("2026-11-02T12:00")]}
    assert detect._timed_cycle(["B", "C", "A"], t) and detect._timed_cycle(["C", "A", "B"], t)
    t[("C", "A")] = [np.datetime64("2026-11-09T12:00")]  # a week later: outside the 3-day window
    assert not detect._timed_cycle(["A", "B", "C"], t)


def test_generated_data_is_labelled_and_network_beats_rules():
    accounts, tx = generator.generate(n_accounts=3000, seed=3)
    assert accounts.label.sum() > 200 and accounts.ring.replace("", np.nan).nunique() == 26
    assert set(tx[tx.laundering == 1].typology) >= {"fan_in", "fan_out", "cycle", "layering", "mule_ring"}
    res = detect.run_all(tx, accounts)
    rules, trail = res["eval"]["rules"], res["eval"]["trail"]
    assert trail["precision"] > rules["precision"] and trail["rings_whole"] > rules["rings_whole"]
    assert trail["cases"] < rules["cases"]


def test_case_flow_roles_and_layers():
    """A chain reads entry → pass → exit, left to right; a pure cycle has no entry, so its first sender starts it."""
    import pandas as pd

    from app.ml.fraud.run import _flow

    acc = pd.DataFrame({"account": list("ABCDXY"), "bank": ["Bank A"] * 6}).set_index("account")
    ts = pd.date_range("2026-11-03 09:00", periods=4, freq="h")
    t = lambda rows: pd.DataFrame(rows, columns=["ts", "src", "dst", "amount", "cross_bank"])  # noqa: E731
    chain = t([(ts[0], "A", "B", 100_000, 1), (ts[1], "B", "C", 98_000, 0)])
    into, outof = t([(ts[0], "X", "A", 101_000, 1)]), t([(ts[2], "C", "Y", 97_000, 1)])
    f = _flow({"A", "B", "C"}, chain, into, outof, acc)
    nodes = {n["id"]: (n["role"], n["layer"]) for n in f["nodes"]}
    assert nodes == {"A": ("entry", 0), "B": ("pass", 1), "C": ("exit", 2)}
    assert [e["kind"] for e in f["events"]] == ["in", "inside", "inside", "out"]
    assert f["in_edges"][0]["d"] == "A" and f["out_edges"][0]["s"] == "C"

    cycle = t([(ts[0], "B", "C", 50_000, 1), (ts[1], "C", "D", 49_000, 1), (ts[2], "D", "B", 48_000, 1)])
    f = _flow({"B", "C", "D"}, cycle, t([]), t([]), acc)
    nodes = {n["id"]: (n["role"], n["layer"]) for n in f["nodes"]}
    assert nodes == {"B": ("start", 0), "C": ("pass", 1), "D": ("pass", 2)}


def test_pattern_is_read_from_the_transfers():
    from app.ml.fraud.run import pattern
    assert pattern([("a", "b"), ("b", "c"), ("c", "a")])["key"] == "cycle"
    assert pattern([("a", "b"), ("b", "c"), ("c", "d")])["key"] == "chain"
    fan = pattern([("a", "h"), ("b", "h"), ("c", "h"), ("h", "x")])
    assert fan["key"] == "fan_in" and fan["hub"] == "h"
    assert pattern([("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")])["key"] == "scatter_gather"


def test_note_keeps_only_transfers_that_exist():
    from app.ml.fraud.explain import Cited, Note, _grounded
    d = {"timeline": [{"ts": "2026-11-05 10:24:00", "src": "A", "dst": "B", "amount": 179822.0, "cross_bank": 0}]}
    note = Note(headline="h", why_flagged=["w"], connections="c", next_steps=["n"], caveats="x", transfers=[
        Cited(ts="wrong", src="A", dst="B", amount=179822, why="real"),
        Cited(ts="2026-11-05 11:00:00", src="B", dst="C", amount=5000, why="invented")])
    out = _grounded(note, d)
    assert [t.why for t in out.transfers] == ["real"] and out.transfers[0].ts == "2026-11-05 10:24:00"
