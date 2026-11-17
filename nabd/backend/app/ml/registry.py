"""Model registry and run log, so every figure on screen traces to a run (CBUAE Model Management Standards).

- MODELS: one card per model (purpose, method, data, validation, limits, owner, risk tier).
- runs: every fit or computation that produces displayed numbers, with inputs, data as-of time and metrics.
"""

from __future__ import annotations

import json
import time
import uuid

from ..core.db import conn

SQL = """
CREATE TABLE IF NOT EXISTS model_runs (
  id TEXT PRIMARY KEY, model TEXT NOT NULL, version TEXT NOT NULL, created REAL NOT NULL,
  data_asof TEXT, params TEXT, metrics TEXT, subject TEXT
);
CREATE INDEX IF NOT EXISTS model_runs_model ON model_runs(model, created);
"""
_ready = False

MODELS = {
    "risk": {
        "name": "Reserve risk model", "version": "1.0", "tier": "High",
        "purpose": "Tracking error against the SAA, share of the active risk budget, marginal risk, VaR and ES",
        "method": "Daily returns over 3 years; exponentially weighted covariance (half-life 126 days) with "
                  "Ledoit-Wolf shrinkage; historical VaR and expected shortfall",
        "data": "Yahoo Finance daily prices (ETFs as index proxies)",
        "validation": "VaR backtest exceptions over the last 250 days, reported with every run",
        "limits": "ETF proxies, not mandate holdings; linear risk; history from 2016",
    },
    "regime": {
        "name": "Market regime model", "version": "1.0", "tier": "Medium",
        "purpose": "Probability that markets are calm, normal or in stress",
        "method": "Three-state Gaussian hidden Markov model on weekly US equity returns, log VIX and credit "
                  "returns (corporates against Treasuries)",
        "data": "Yahoo Finance (SPY, LQD, IEF), FRED (VIXCLS)",
        "validation": "State persistence and the stress state's overlap with known episodes (2018 Q4, 2020, 2022)",
        "limits": "Unsupervised; state labels are assigned by volatility; US-centric inputs",
    },
    "ranker": {
        "name": "Return-ranking model", "version": "1.0", "tier": "Medium",
        "purpose": "Rank instruments by expected 3-month return relative to the US market; one screening input",
        "method": "Gradient-boosted trees on momentum, volatility, drawdown, beta, macro betas and regime, "
                  "trained walk-forward each month",
        "data": "Yahoo Finance prices, FRED macro, regime model output",
        "validation": "Out-of-sample rank correlation (IC) and hit rate per month, shown on screen",
        "limits": "Weak signal by nature; never used alone; no transaction costs",
    },
    "stress": {
        "name": "Scenario and stress engine", "version": "1.0", "tier": "High",
        "purpose": "Portfolio and tilt outcomes under historical replays, factor shocks and simulation",
        "method": "Replays of actual returns in past windows; factor shocks through estimated macro betas; "
                  "block-bootstrap Monte Carlo (10-day blocks, 2,000 paths, 63 days)",
        "data": "Yahoo Finance prices, FRED macro",
        "validation": "Replays use realised returns; factor-shock fits report R²",
        "limits": "Linear betas understate extreme moves; replays only from 2016",
    },
    "fraud": {
        "name": "Fraud-network detection", "version": "1.0", "tier": "High",
        "purpose": "Find laundering and mule networks in instant payments, as cases investigators can open whole",
        "method": "Rules baseline; money-trail tracing of pass-through transfers via mule accounts; Louvain "
                  "communities; time-ordered cycles; gradient-boosted trees on account features (cross-fitted by "
                  "ring); a combined network method",
        "data": "Synthetic AMLSim-style payments across six banks, with labelled typologies and legitimate look-alikes",
        "validation": "Precision, recall and rings caught whole against the labels; ML scored out of fold",
        "limits": "Synthetic data until CBUAE payment data is available on premise; thresholds need calibration on "
                  "real flows",
    },
    "nowcast": {
        "name": "UAE GDP nowcast (Kalman, with and without AI news)", "version": "2.0", "tier": "High",
        "purpose": "Nowcast quarterly real and non-oil GDP growth (y/y) before FCSC publishes, and measure what "
                   "LLM-read news adds to the same model",
        "method": "Dynamic factor model with GDP in the state, Kalman filter and smoother (two-step estimation), in "
                  "three versions: hard data; plus GDELT tone; plus AI news signals (LLM labels of UAE business "
                  "headlines, labelled blind to dates, as a monthly diffusion index with shrinkage). Exact contribution "
                  "and revision breakdowns",
        "data": "FCSC first releases, IMF PortWatch, Yahoo Finance, GDELT GKG headlines and tone, Codex labels",
        "validation": "Pseudo real-time backtest at three points per quarter against first releases; coverage of the "
                      "model's own 70% and 90% bands",
        "limits": "13 released quarters, one contraction; headlines are a sample of GDELT's English feed; LLM "
                  "labels are blind to dates but the model may still recognise famous events from a headline's text",
    },
    "thesis": {
        "name": "Thesis parser and research writer (LLM)", "version": "1.0", "tier": "Medium",
        "purpose": "Turn free text into a structured thesis; draft research notes and committee cover notes",
        "method": "Codex with Nabd tools; structured output; every figure comes from a tool result",
        "data": "Tool outputs only; no figures from the model's own knowledge",
        "validation": "Human review at every stage; figures traced to tool calls",
        "limits": "Codex demo provider sends prompts to OpenAI: open data only",
    },
}


def _init():
    global _ready
    if not _ready:
        conn().executescript(SQL)
        _ready = True


def record(model: str, params: dict | None = None, metrics: dict | None = None, subject: str | None = None,
           data_asof: str | None = None) -> str:
    _init()
    run_id = f"{model}-{uuid.uuid4().hex[:8]}"
    conn().execute(
        "INSERT INTO model_runs(id,model,version,created,data_asof,params,metrics,subject) VALUES(?,?,?,?,?,?,?,?)",
        (run_id, model, MODELS[model]["version"], time.time(), data_asof, json.dumps(params or {}, default=str),
         json.dumps(metrics or {}, default=str), subject),
    )
    return run_id


def get(run_id: str) -> dict | None:
    _init()
    r = conn().execute("SELECT * FROM model_runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["params"], d["metrics"] = json.loads(d["params"]), json.loads(d["metrics"])
    return d


def latest(model: str, limit: int = 10) -> list[dict]:
    _init()
    rows = conn().execute("SELECT id FROM model_runs WHERE model=? ORDER BY created DESC LIMIT ?", (model, limit))
    return [get(r["id"]) for r in rows]
