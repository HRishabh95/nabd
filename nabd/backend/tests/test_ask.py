import pytest

from app.agents import ask


def test_calc_does_arithmetic_and_refuses_anything_else():
    assert ask.calc("(48.1 - 11.6) / 2")["value"] == 18.25
    assert ask.calc("2^3")["value"] == 8
    for bad in ("__import__('os')", "open('x')", "a + 1"):
        with pytest.raises(ValueError):
            ask.calc(bad)


def test_figure_check_uses_paragraph_citations_and_ignores_dates():
    ev = {"E1": {"tool": "series_data", "args": {}, "result": {"stats": {"XLE": {"last": 147.913, "change": 47.913}}}}}
    text = "XLE ended at 147.9 on 13 November 2026, up 47.9%. That is strong.\n- Since 2025-11-17 it is up 47.9% [E1]"
    out = ask.figure_check(text + " [E1]", ev)
    assert out == {"figures": 3, "traced": 3, "untraced": []}
    assert ask.figure_check("XLE rose 99.9% [E1].", ev)["untraced"] == ["99.9"]


def test_charts_are_built_from_tool_data_and_capped_at_four_series():
    ds = {"kind": "line", "x": ["2026-01-02", "2026-01-09"], "unit": "level",
          "series": {f"S{i}": [1.0, 2.0] for i in range(6)}}
    charts = ask.build_charts([{"type": "line", "title": "t", "evidence": ["E1", "E9"], "y_label": "level"}],
                              {"E1": {"dataset": ds}})
    assert len(charts) == 1 and len(charts[0]["series"]) == 4 and charts[0]["evidence"] == ["E1"]
    assert ask.build_charts([{"type": "bar", "title": "t", "evidence": ["E2"], "y_label": ""}], {"E2": {}}) == []


def test_partial_answer_is_read_from_streaming_json():
    assert ask._answer_so_far('{"answer":"Brent rose 4') == "Brent rose 4"
    assert ask._answer_so_far('{"answer":"Line one\\nLine') == "Line one\nLine"
    assert ask._answer_so_far('{"charts": [') is None
