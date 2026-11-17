"""Model governance and AI evaluation: what a Head of AI or the CRO asks for.

- Evaluation of the AI outputs, from what the app already checks on every run (research claims verified and figures
  traced; Ask Nabd figures traced; fraud-note transfers matched to the data), plus human review (thumbs up or down with
  a comment on any AI output) and a measured accuracy for the news labels (an analyst labels a sample of headlines
  without seeing the AI's label; agreement is computed, never assumed).
- A validation pack per model, generated from the model card and its actual runs: purpose, data, method, results,
  limits, monitoring, change history and sign-off. It is the document a validator would review; it does not claim
  that a validation has happened.
"""

from __future__ import annotations

import html
import json
import random
import time

from ..core.db import conn
from ..core.db import store as kv
from ..ml import registry

SQL = """
CREATE TABLE IF NOT EXISTS ai_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL,
  verdict INTEGER NOT NULL, comment TEXT, reviewer TEXT
);
CREATE TABLE IF NOT EXISTS human_labels (
  id TEXT PRIMARY KEY, ts REAL NOT NULL, relevant INTEGER NOT NULL, direction INTEGER, reviewer TEXT
);
"""
_ready = False
KINDS = {"research": "Deep research reports", "fraud_note": "Fraud investigation notes", "ask": "Ask Nabd answers",
         "thesis": "Idea theses", "proposal": "What-to-look-at proposals"}


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        _ready = True


# ---- human review ---------------------------------------------------------------------------------------------------

def review(kind: str, ref: str, verdict: int, comment: str = "", reviewer: str = "Investment team") -> dict:
    _init()
    conn().execute("INSERT INTO ai_feedback(ts,kind,ref,verdict,comment,reviewer) VALUES(?,?,?,?,?,?)",
                   (time.time(), kind, ref, 1 if verdict > 0 else -1, comment.strip()[:500], reviewer))
    kv.audit(reviewer, "ai_review", f"{kind}:{ref}", {"verdict": verdict, "comment": comment[:200]})
    return reviews_for(kind, ref)


def reviews_for(kind: str, ref: str) -> dict:
    _init()
    rows = conn().execute("SELECT ts, verdict, comment, reviewer FROM ai_feedback WHERE kind=? AND ref=? ORDER BY ts DESC",
                          (kind, ref)).fetchall()
    return {"kind": kind, "ref": ref, "up": sum(r["verdict"] > 0 for r in rows), "down": sum(r["verdict"] < 0 for r in rows),
            "latest": [dict(r) for r in rows[:5]]}


# ---- headline labels: measured accuracy -----------------------------------------------------------------------------

def label_sample(n: int = 10) -> list[dict]:
    """Headlines the AI labelled and no person has yet; shown without the AI's label so the person is not anchored."""
    _init()
    rows = conn().execute("SELECT a.id, a.title FROM news_archive a JOIN news_labels l ON a.id=l.id "
                          "LEFT JOIN human_labels h ON a.id=h.id WHERE h.id IS NULL").fetchall()
    random.shuffle(rows)
    return [{"id": r["id"], "title": r["title"]} for r in rows[:n]]


def add_label(item_id: str, relevant: bool, direction: int | None, reviewer: str = "Analyst") -> None:
    _init()
    conn().execute("INSERT OR REPLACE INTO human_labels VALUES(?,?,?,?,?)",
                   (item_id, time.time(), int(relevant), direction if relevant else None, reviewer))


def label_agreement() -> dict:
    _init()
    rows = conn().execute("SELECT h.relevant hr, h.direction hd, l.relevant ar, l.direction ad FROM human_labels h "
                          "JOIN news_labels l ON h.id=l.id").fetchall()
    n = len(rows)
    if not n:
        return {"n": 0}
    rel = sum(r["hr"] == r["ar"] for r in rows)
    both = [r for r in rows if r["hr"] and r["ar"]]
    exact = sum(r["hd"] == r["ad"] for r in both)
    near = sum(abs((r["hd"] or 0) - (r["ad"] or 0)) <= 1 for r in both)
    sign = sum((r["hd"] or 0) * (r["ad"] or 0) > 0 or (r["hd"] or 0) == (r["ad"] or 0) == 0 for r in both)
    # Cohen's kappa on relevance: agreement beyond what chance would give
    p_o = rel / n
    ph, pa = sum(r["hr"] for r in rows) / n, sum(r["ar"] for r in rows) / n
    p_e = ph * pa + (1 - ph) * (1 - pa)
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else 1.0
    return {"n": n, "relevance_agree": round(rel / n, 3), "relevance_kappa": round(kappa, 3), "both_relevant": len(both),
            "direction_exact": round(exact / len(both), 3) if both else None,
            "direction_within_1": round(near / len(both), 3) if both else None,
            "direction_same_sign": round(sign / len(both), 3) if both else None}


# ---- automatic checks -----------------------------------------------------------------------------------------------

def evaluation() -> dict:
    from ..invest import ideas

    _init()
    research = []
    for i in ideas.all_ideas(include_deleted=True):  # a deleted idea's research was still produced and checked
        st = ((i.get("research") or {}).get("verification") or {}).get("stats")
        if st:
            research.append({"idea": i["id"], "title": (i.get("thesis") or {}).get("title") or i["title"],
                             "claims": st.get("claims", 0), "unsupported": st.get("unsupported", 0),
                             "figures": st.get("figures_checked", 0), "traced": st.get("figures_traced", 0)})
    notes = [v for k, v in ((r["key"], json.loads(r["value"])) for r in
             conn().execute("SELECT key, value FROM kv WHERE key LIKE 'fraud:note:%'")) if isinstance(v, dict)]
    asks = []
    for r in conn().execute("SELECT id, data FROM ask_messages WHERE role != 'user' AND data IS NOT NULL"):
        try:
            c = (json.loads(r["data"]) or {}).get("check") or {}
        except ValueError:
            continue
        if c.get("figures"):
            asks.append(c)
    fb = conn().execute("SELECT kind, SUM(verdict>0) up, SUM(verdict<0) down, COUNT(*) n FROM ai_feedback GROUP BY kind").fetchall()
    recent = conn().execute("SELECT ts, kind, ref, verdict, comment, reviewer FROM ai_feedback ORDER BY ts DESC LIMIT 12").fetchall()
    return {
        "research": {"runs": len(research), "claims": sum(x["claims"] for x in research),
                     "removed": sum(x["unsupported"] for x in research), "figures": sum(x["figures"] for x in research),
                     "traced": sum(x["traced"] for x in research), "items": research},
        "fraud_notes": {"notes": len(notes), "cited": sum((n.get("checked") or {}).get("cited", 0) for n in notes),
                        "matched": sum((n.get("checked") or {}).get("matched", 0) for n in notes)},
        "ask": {"answers": len(asks), "figures": sum(c["figures"] for c in asks), "traced": sum(c.get("traced", 0) for c in asks)},
        "labels": label_agreement(),
        "feedback": {"by_kind": [{"kind": r["kind"], "label": KINDS.get(r["kind"], r["kind"]), "up": r["up"], "down": r["down"], "n": r["n"]} for r in fb],
                     "recent": [dict(r) for r in recent]},
    }


# ---- validation pack --------------------------------------------------------------------------------------------------

def _metrics_table(m: dict) -> str:
    rows = []
    for k, v in (m or {}).items():
        if isinstance(v, dict):
            inner = ", ".join(f"{a}: {b}" for a, b in v.items() if not isinstance(b, (dict, list)))
            rows.append(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(inner)}</td></tr>")
        elif not isinstance(v, list):
            rows.append(f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>")
    return "<table>" + "".join(rows) + "</table>" if rows else "<p>No metrics recorded.</p>"


def _results(key: str) -> str:
    """Model-specific results from its latest stored run."""
    if key == "nowcast":
        from ..ml.forecasting import ai_eval
        out = ai_eval.stored()
        if not out:
            return "<p>No run yet.</p>"
        parts = []
        for t, v in out["targets"].items():
            rows = "".join(f"<tr><td>{s['model']}</td><td>{s['horizon']}</td><td>{s['n']}</td><td>{s['rmse']}</td>"
                           f"<td>{s.get('rmse_excl_shock')}</td><td>{s.get('cover70', '')}</td></tr>"
                           for s in v["backtest"]["scores"])
            parts.append(f"<h3>{html.escape(v['label'])}</h3><table><tr><th>Model</th><th>When</th><th>Quarters</th>"
                         f"<th>RMSE (pp)</th><th>RMSE without Q2 2026</th><th>70% band held</th></tr>{rows}</table>")
        return "".join(parts) + "<p>Pseudo real-time: each nowcast used only data published by its date; scored against FCSC first releases.</p>"
    if key == "fraud":
        from ..ml.fraud import run
        out = run.latest()
        if not out:
            return "<p>No run yet.</p>"
        allm = {**out.get("benchmarks", {}), **out["methods"]}
        rows = "".join(f"<tr><td>{html.escape(v['label'])}</td><td>{v['eval']['precision']}</td><td>{v['eval']['recall']}</td>"
                       f"<td>{v['eval']['f1']}</td><td>{v['eval']['cases']}</td><td>{v['eval']['rings_whole']}/{v['eval']['rings']}</td></tr>"
                       for v in allm.values())
        return (f"<table><tr><th>Method</th><th>Precision</th><th>Recall</th><th>F1</th><th>Cases</th><th>Rings caught whole</th></tr>{rows}</table>"
                f"<p>Measured against the labels of synthetic payment data ({out['data']['accounts']} accounts, "
                f"{out['data']['transfers']} transfers). Real performance will be lower.</p>")
    runs = registry.latest(key, 1)
    return _metrics_table(runs[0]["metrics"]) if runs else "<p>No run yet.</p>"


def pack(key: str) -> str:
    from ..api.monitor import _model_status

    card = registry.MODELS.get(key)
    if not card:
        raise KeyError(key)
    st = _model_status(key)
    runs = registry.latest(key, 10)
    esc = lambda s: html.escape(str(s or ""))  # noqa: E731
    hist = "".join(f"<tr><td>{esc(r['id'])}</td><td>{time.strftime('%d %b %Y %H:%M', time.localtime(r['created']))}</td>"
                   f"<td>{esc(r.get('data_asof'))}</td><td>{esc(r.get('version'))}</td></tr>" for r in runs)
    today = time.strftime("%d %B %Y")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Validation pack: {esc(card['name'])}</title>
<style>body{{font:14px/1.5 -apple-system,Segoe UI,sans-serif;max-width:820px;margin:32px auto;padding:0 20px;color:#1d1d1f}}
h1{{font-size:24px}}h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #ddd;padding-bottom:4px}}h3{{font-size:14px}}
table{{border-collapse:collapse;width:100%;margin:8px 0}}td,th{{border:1px solid #ddd;padding:5px 8px;text-align:left;font-size:13px}}
th{{background:#f5f5f7}}.status{{padding:10px 14px;background:#fff4e5;border:1px solid #f0c27a;border-radius:8px}}
@media print{{body{{margin:0}}}}</style></head><body>
<p>Nabd · Central Bank of the UAE · proof of concept</p>
<h1>Validation pack: {esc(card['name'])}</h1>
<p class="status"><b>Status:</b> {esc(st.get('status', 'watch'))}. Development (proof of concept). <b>Not yet independently validated.</b>
This pack is generated from the model's card and its recorded runs on {today}, for review by an independent validator.</p>
<table><tr><th>Model ID</th><td>{esc(key)}</td><th>Version</th><td>{esc(card.get('version'))}</td></tr>
<tr><th>Risk tier</th><td>{esc(card.get('tier'))}</td><th>Owner</th><td>To be assigned by CBUAE</td></tr></table>
<h2>1. Purpose and intended use</h2><p>{esc(card.get('purpose'))}</p>
<h2>2. Data</h2><p>{esc(card.get('data'))}</p>
<h2>3. Method</h2><p>{esc(card.get('method'))}</p>
<h2>4. Validation approach used by the developer</h2><p>{esc(card.get('validation'))}</p>
<h2>5. Results from the latest run</h2>{_results(key)}
<p><b>Live monitoring:</b> {esc(st.get('metric'))} {('· ' + esc(st.get('reason'))) if st.get('reason') else ''}</p>
<h2>6. Assumptions and limitations</h2><p>{esc(card.get('limits'))}</p>
<h2>7. Sensitivity</h2><p>Inputs can be switched on and off in the app and the model re-tested on the same backtest
(Forecasting · Test the nowcast); detection thresholds are run parameters recorded with each run.</p>
<h2>8. Controls and implementation</h2><ul><li>Every run is recorded with its parameters, data date and metrics (run history below).</li>
<li>LLM outputs never supply figures: figures come from tools and are traced; cited items are checked against the data.</li>
<li>Every stage and decision is written to the audit log with the actor and time.</li></ul>
<h2>9. Run history</h2><table><tr><th>Run</th><th>When</th><th>Data as of</th><th>Version</th></tr>{hist}</table>
<h2>10. Open items for the validator</h2><ul><li>Independent replication of the results in section 5.</li>
<li>Review of data lineage and of the limitations in section 6.</li><li>Agreement of thresholds and monitoring limits with Risk.</li></ul>
<h2>11. Sign-off</h2><table><tr><th>Role</th><th>Name</th><th>Date</th><th>Decision</th></tr>
<tr><td>Model developer</td><td></td><td></td><td></td></tr><tr><td>Model owner</td><td></td><td></td><td></td></tr>
<tr><td>Independent validator</td><td></td><td></td><td></td></tr><tr><td>Approver</td><td></td><td></td><td></td></tr></table>
<p style="color:#6e6e73;font-size:12px">Structured as conventional model documentation (purpose, data, method, performance, limitations,
monitoring, change control, sign-off) to support review under CBUAE's model management framework; check against the current Standards.</p>
</body></html>"""
