from app.invest import verify

EVIDENCE = {
    "E1": {"tool": "event_study", "args": {"symbols": ["MUFG"]}, "result": {"car_pct_end": 4.79, "t_end": 3.42,
                                                                            "hit_rate_end": 0.857, "events": 21}},
    "E2": {"tool": "price_stats", "args": {"symbol": "XLE"}, "result": {"avg_daily_value_traded_usd_mn": 2394.6,
                                                                        "return_1y_pct": -5.7}},
}


def test_numbers_trace_with_rounding_percent_and_units():
    m = verify.mechanical({"text": "Banks beat the index by 4.8% (t 3.4) in 85.7% of 21 events [E1]",
                           "evidence": ["E1"]}, EVIDENCE)
    assert m["untraced"] == [] and m["numbers"] == 4  # 4.8, 3.4, 85.7 and 21 all trace to E1
    m = verify.mechanical({"text": "XLE trades USD 2.39 bn a day and fell 5.7% over the year", "evidence": ["E2"]},
                          EVIDENCE)
    assert m["untraced"] == []


def test_untraced_figure_and_missing_evidence_are_caught():
    m = verify.mechanical({"text": "Returns were 12.5% higher", "evidence": ["E1", "E9"]}, EVIDENCE)
    assert m["untraced"] == ["12.5"] and m["missing_evidence"] == ["E9"]


def test_years_and_ids_are_not_treated_as_figures():
    assert verify._numbers_in_text("In 2024 the E12 result and H3 test") == []


def test_unsupported_claims_are_removed_from_findings():
    state = {"findings": {"H1": {"evidence_for": [{"text": "a", "evidence": ["E1"]}, {"text": "b", "evidence": []}],
                                 "evidence_against": []}},
             "verification": {"claims": [{"id": "H1.for.0", "status": "supported"},
                                         {"id": "H1.for.1", "status": "unsupported"}]}}
    kept = verify.filtered_findings(state)["H1"]["evidence_for"]
    assert [p["text"] for p in kept] == ["a"] and kept[0]["check"] == "supported"


def test_plan_framing_never_claims_tests_were_not_run():
    from app.invest.deep import clean_framing
    t = ("MRMC must establish whether AI exposure justifies a reduction within the SAA and Board risk budget; the tests "
         "below remain unexecuted because Nabd research tools are unavailable in this session, so no evidence IDs have "
         "been generated.")
    assert clean_framing(t) == "MRMC must establish whether AI exposure justifies a reduction within the SAA and Board risk budget."
    assert clean_framing("Establish whether bank margins widen.") == "Establish whether bank margins widen."
