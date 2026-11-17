# Nabd POC — end-to-end build plan

Status: phases 0–7 built, plus deep research · 16 Nov 2026
Goal: turn the clickable prototype (`nabd-prototype/`) into a working POC with a real backend, real model runs,
open data, a Codex-backed assistant, streaming, and continuous monitoring. Four pages stay as designed:
Overview, Forecasting, Fraud network, Investment.

---

## 1. What "end to end" means for this POC

| Page | Real in the POC | Still synthetic (swap point for CBUAE data) |
|---|---|---|
| Forecasting | Open macro, market, shipping and news data; 5 models trained and backtested on demand; runs streamed live | Payment flows (UAEFTS, Aani, WPS, cards) are not public. A labelled generator calibrated to public aggregates stands in |
| Fraud network | Graph algorithms run on a real open AML benchmark with ground-truth labels; user picks method and thresholds; runs streamed | UAE bank names and Aani specifics |
| Investment | Real public-market prices, macro and news; a notional portfolio; a public-markets deal pipeline; scenario stress | Holdings are a model portfolio, not CBUAE's |
| Ask Nabd | Codex answers, but every figure and chart is computed by the backend's tools, not written by the LLM; answers stream | — |
| Monitoring | Scheduled refresh of every source; alert rules on data, models, portfolio and fraud; alerts pushed live | — |

---

## 2. Open data sources

Each connector caches raw pulls to `data/raw/` (parquet) with a retrieval timestamp, so backtests can use
*vintages*: only what was knowable on a date.

**Macro and the GDP target**
- FCSC quarterly GDP, total and non-oil (fcsc.gov.ae GDP – Quarterly, Bayanat.ae). Snapshot as CSV with release
  dates. Note: FCSC is revising its historical series, so keep the vintages.
- IMF data API (WEO, IFS) and World Bank WDI: annual anchors and cross-checks.
- FRED (free API key): Brent `DCOILBRENTEU`, US Treasury yields, US dollar index, global rates.
- CBUAE monthly statistics (money supply, credit to the private sector): Excel downloads, parsed monthly.
- OECD composite leading indicators: open substitute for PMIs, which are not open.

**High-frequency activity proxies (open)**
- IMF PortWatch: daily Strait of Hormuz transits and UAE port calls (Jebel Ali, Khalifa) from AIS; via the PortWatch
  ArcGIS service, with straits.live CSV as a fallback. Cite IMF.
- Dubai Pulse open data: Dubai Land Department transactions (daily).
- GDELT 2.0 DOC API (no key): news volume and tone by query, Arabic and English (shipping and Hormuz, construction,
  tourism, property, oil). This is the news input to the nowcast.

**Public markets (Investment page)** (built in phase 1)
- **Yahoo Finance chart endpoint, called directly**, about 10 years of daily prices for 160 instruments:
  - The `yfinance` library failed from this network; the endpoint itself works.
  - The data is unofficial; a licensed feed replaces it in production.
  - Dubai-listed names work (`.AE`). Yahoo serves no single Abu Dhabi (ADX) stocks and no history for the FTSE
    ADX index, so UAE exposure comes from Dubai names and the MSCI UAE ETF.
- **Stooq was dropped.** It now sits behind a browser-verification check, which is bot protection, and Nabd does
  not get around it.
- **SEC EDGAR** for filings and reported fundamentals. SEC requires a requester name and contact email, so it stays
  off until `NABD_SEC_USER_AGENT` is set. Nabd never fills in a contact.
- **FRED** through the public CSV, which needs no key: 10 macro series, each with its normal publication lag, so
  "late" means late.

**News** (built in phase 1)
- **GDELT search API: fallback only.** It rate-limits shared networks hard, and from here even the first request
  got a 429.
- **GDELT GKG 2.1 raw files instead**, published every 15 minutes. They come in English and as a feed
  machine-translated from 65 languages, Arabic included.
  - Nabd ingests each new file and samples 30 days back.
  - Per theme (Hormuz, oil, UAE economy, Fed and rates, gold, AI investment) it computes volume (share of world
    coverage), tone and article count.
  - It keeps 14 days of matching headlines.

**Fraud network**
- IBM AMLSim (Apache 2.0, generated locally, no account): accounts, transactions, alerts with labelled typologies
  (fan-in, fan-out, cycles, layering, smurfing). Calibrated to roughly 6 banks and a UAE-sized week.
- Optional: IBM AML benchmark datasets (Altman et al. 2023) from Kaggle, which need your Kaggle login.

---

## 3. Architecture

```
CBUAE/
  nabd/
    backend/                 Python 3.11, FastAPI, uvicorn, pydantic v2, uv
      app/
        main.py              app, lifespan (starts scheduler, monitors, job workers)
        api/                 routers: forecasting, fraud, investment, ask, alerts, stream, system
        core/                config, db (SQLite WAL + DuckDB), event bus, security (local header + same-origin)
        llm/
          gateway.py         one interface: structured(prompt, schema) and stream(...)
          codex_session.py   ported from TradingMaus: `codex app-server` over stdio JSON-RPC
          providers/         codex (dev), azure_openai (UAE North, for the CBUAE environment), local (vLLM)
        data/
          connectors/        fcsc, imf, worldbank, fred, cbuae, portwatch, dubai_pulse, gdelt, yahoo, stooq, edgar
          catalog.py         every series: source, frequency, last refresh, freshness status
          vintages.py        as-of queries for real-time backtests
        ml/
          forecasting/       dfm.py (statsmodels DynamicFactorMQ), midas.py, gbm.py (LightGBM), news.py, ensemble.py, backtest.py
          fraud/             graph.py, communities.py (Louvain/Leiden, label propagation), trails.py, cycles.py,
                             pagerank.py, scoring.py, gnn.py (later), evaluate.py
          portfolio/         prices.py, risk.py (vol, historical VaR, exposures), scenarios.py, attribution.py
        agents/
          ask_nabd.py        planner, tool executor, answer writer
          tools.py           query_series, run_model, portfolio_view, scenario, news_search, make_chart
        jobs/                runner (asyncio queue + process pool), job table, progress events
        monitoring/          scheduler loops, alert rules, alert store
      tests/
    frontend/                Vite + React + TypeScript
      src/
        design/              glass tokens and components ported from the prototype (HIG, Liquid Glass)
        pages/               Overview, Forecasting, FraudNetwork, Investment
        components/          TabBar, Card, Segmented, Switch, ChartRenderer (Vega-Lite), NetworkView (sigma.js)
        lib/                 api client, useEventStream (SSE with polling fallback), query cache
    data/                    raw/, processed/, vintages/ (gitignored)
    docker-compose.yml       backend + frontend (+ optional Postgres later)
    Makefile                 setup, dev, test, refresh-data, demo
    .env.example             FRED_API_KEY, LLM_PROVIDER, model names (no secrets committed)
  docs/
  nabd-prototype/            kept as the design reference
```

**Storage:** SQLite (WAL) for app state (jobs, runs, alerts, audit, pipeline). DuckDB over parquet for time series
and model results. Postgres only if we need multi-user later.

**Streaming (SSE everywhere, typed events, deltas not full state):**
- `GET /api/stream`: global channel with `alert`, `data.refreshed`, `job.progress`, `job.done`, `model.registered`.
- `POST /api/ask` returns a session id; `GET /api/ask/{id}/stream` streams the assistant (see section 5).
- `GET /api/jobs/{id}/stream`: one model run, step by step.
- Heartbeat every 15 s; the client reconnects automatically and falls back to polling if no event arrives for 20 s
  (TradingMaus pattern). Fix TradingMaus's cost issue by sending only changed objects.

**Jobs:** CPU-heavy model training and graph analysis run in a process pool so the API stays responsive. Each run gets
a row (inputs, data vintage, code version, metrics, artefacts) so every number on screen links to a run id.

---

## 4. The three modules

### Forecasting (GDP with news, models the user can pick)
- **Target:** quarterly non-oil GDP growth (FCSC). **Inputs:** Brent, PortWatch transits and port calls, DLD
  transactions, CBUAE money and credit, OECD leading indicators, GDELT news tone and volume, plus the labelled
  synthetic payment series.
- **Models:** dynamic factor model (mixed frequency), MIDAS regression, gradient-boosted trees, a news model (GDELT
  features, with the LLM classifying headlines into topics), and an ensemble. Benchmarks: autoregression and an
  oil-plus-leading-indicator bridge.
- **Evaluation:** pseudo real-time backtest using vintages; error by horizon; champion and challenger; drift checks.
- **UI:** model picker and compare (as in the prototype), "Run backtest" streams progress, every chart shows its run id.

### Fraud network (methods the user can run)
- Build the transaction graph from AMLSim output (networkx; igraph if speed requires).
- **Methods:** money-trail tracing (temporal pass-through components), community detection (Louvain/Leiden, label
  propagation), cycle detection (bounded), PageRank on money flows, fan-in/fan-out, and a supervised LightGBM baseline
  on node features. A graph neural network (GraphSAGE) is a stretch goal.
- **Evaluation against the labels:** precision, recall, rings recovered whole versus fragmented, false alarms. This
  is the "network beats rules" proof.
- **UI:** method and thresholds picker, "Run detection" streams progress, the network rendered with sigma.js (WebGL),
  so thousands of accounts stay smooth.

### Investment (public-markets pipeline, portfolio, news and macro, Ask Nabd)
The full design is in section 4A. In short: Idea → Screening → Research → Portfolio fit → Stress → Committee →
Position and exit plan → Monitoring, which loops back to Idea.
- **Portfolio:** notional AED 100 bn model portfolio; daily P&L, volatility, historical VaR, sector and country
  exposure, attribution; scenario stress (Hormuz closure, oil shock, rates shock) linked to the forecasting module.
- **Ask Nabd:** chat that answers with text and charts (section 5); suggested questions per page.
- **Monitoring:** price moves, drawdown, limit breaches, news-tone spikes per holding, pushed as alerts.

---

## 4A. Investment, designed around how CBUAE actually invests

### What kind of investor CBUAE is (from public sources)
- **A public-sector reserve manager investing in public markets only.** It is not a private-markets investor like
  Mubadala or ADQ. It manages the UAE's official foreign-currency reserves: net USD 285 bn at end-2025, up from
  USD 231 bn. Assets are mostly high-quality liquid assets (CBUAE Annual Report 2025, 2024).
- **Tranches:** money market (daily liquidity), capital market (return and diversification), gold (inflation hedge,
  diversification) and long-term investment (Central Banking reserve-manager award profile). Gold rose to
  AED 37.9 bn in 2025.
- **2025–2029 Strategic Asset Allocation, approved by the Board:** more international government bonds and
  "measured exposure to developed-market equities", plus new tranches for liquidity and diversification.
- **External managers:** allocations grew in 2025. New asset classes start with passive mandates, many benchmarked
  to indices with socially responsible investment (SRI) screens.
- **Governance:**
  - The Board approves the investment policy, the SAA, the risk tolerance and the active risk budget.
  - The Monetary and Reserve Management Committee (MRMC) approves tactical allocation and investment guidelines and
    meets at least four times a year.
  - Risk management is a separate function, the second line. FX reserves must cover at least 70% of the monetary
    base. The policy follows the IMF reserve-management guidelines.

**What this means for the POC.** The decision CBUAE actually takes is rarely "buy one stock". It is closer to:
- tilt the developed-market equity tranche toward a theme or region;
- hire or resize a passive or SRI mandate;
- change bond duration;
- add gold.

So the pipeline's unit is an **investment idea**, expressed as a basket of instruments. The basket can mix
index and ETF exposures (country, sector, factor, SRI, government bonds, gold) with single developed-market equities
for research depth. It is always judged as an **active tilt against the SAA benchmark, inside the Board's risk
budget**. That framing is what makes it credible to the Investment team and the CRO, and what a chatbot cannot do.

### The flow (one idea, end to end)
| Stage | What the user does | What Nabd computes (backend, not the LLM) | LLM role |
|---|---|---|---|
| 1. Idea | Types a free-text idea and picks the horizon: **tactical** (1–6 months, goes to MRMC) or **strategic** (years, goes to the SAA review and the Board) | Links the idea to the tranche and to the current macro regime and nowcast | Parses the text into a structured thesis: direction, themes, regions, horizon, drivers, and "what would prove us wrong". The user edits it |
| 2. Screening | Reviews a ranked list and selects 3–8 instruments | Thesis fit (sector, region and theme tags); factors (momentum, low volatility, value, quality); the ML expected-return rank with its honest hit rate; liquidity; SRI flag | Tags company descriptions to themes once, cached; never ranks |
| 3. Research | Opens each selected instrument | Price and drawdown history; macro betas (oil, USD, UST 10y, VIX, gold); news volume and tone (GDELT); filings (EDGAR); past ideas on the same names, from memory | Writes a research note in which every claim cites a tool result |
| 4. Portfolio fit | Proposes a size, or asks Nabd for the largest size that fits | Ex-ante tracking error against the SAA benchmark; share of the active risk budget used; marginal contribution to risk; correlation with current holdings; concentration; liquidity days; change in VaR and expected shortfall | Explains the trade-offs |
| 5. Stress and scenarios | Picks scenarios | **Historical replays:** 2008, March 2020, 2022 rates, the 2014 oil collapse, the 2019 Abqaiq attack. **Factor shocks:** Hormuz closure, oil, rates, USD; Hormuz is linked to the Forecasting page's nowcast. **Monte Carlo:** block-bootstrap distribution of 3-month P&L | Summarises the outcomes |
| 6. Committee (MRMC) | Sends the idea to committee and records the decision with its conditions | Assembles the pack: thesis, evidence, fit, stress, exit plan, the models used, and every number with its run id. **A separate Risk sign-off slot for the second line** | Drafts the cover note from the pack |
| 7. Position and exit plan | Approves the exit rules | Stored triggers: target, drawdown limit, time stop, thesis-invalidation conditions (macro, news, regime), and rebalance back to benchmark | — |
| 8. Monitoring | Gets alerts and reviews them | Checked on every refresh: P&L against the benchmark, risk-budget use, each trigger, news tone, and a **thesis-health score**. A breached trigger raises an alert and opens a review. The loop goes back to stage 1 | Explains why the thesis weakened, citing the data |

**Universe for the POC (open data):**
- About 40 ETFs as index proxies: country, sector, factor, SRI, government bond (by duration) and gold.
- About 150 developed-market large caps across sectors.
- A few UAE names for context.

The model reserve portfolio is notional, about USD 285 bn split across the four tranches. It is clearly labelled
as notional, not CBUAE's holdings.

### Built in phase 2 (16 Nov 2026), with measured results
- **Notional reserve portfolio:** USD 285 bn across four tranches. Gold is 4%, matching the published AED 37.9 bn,
  and developed-market equity 13% through SRI-index lines. The active risk budget of 60 bp tracking error is an
  assumption.
- **Risk model:** EWMA plus Ledoit-Wolf covariance over 3 years, with tracking error, budget use, marginal
  contributions, historical VaR and ES, and a VaR backtest (4 exceptions in 250 days against a limit of 4).
- **Regime model:** three-state hidden Markov model on 10 years of weekly data. FRED's ICE high-yield spread covers
  only 3 years (licence), so the credit input is LQD minus IEF. Average stress probability: 0.90 in the COVID crash,
  0.93 in the 2022 rates shock, 0.39 in the 2018 Q4 sell-off.
- **Return-ranking model:** gradient-boosted trees trained walk-forward. Out of sample over 86 months: rank IC 0.036
  (t-statistic 1.54), hit rate 59%, top minus bottom quintile +1.7% a quarter. That is weak and shown as weak.
- **Stress engine:** five replays (2018 Q4, Abqaiq 2019, COVID, 2022 rates, 2025 tariffs), four factor shocks
  (Hormuz included) and 2,000-path block-bootstrap Monte Carlo.
- **Codex with live tool calling:**
  - A thesis parser whose tags are restricted to the universe's vocabulary.
  - A research writer that uses 8 tools and cites evidence IDs (27 to 32 pieces of evidence per note in testing).
  - A committee cover note that quotes the pack exactly and never recommends a decision.
  - A post-mortem lesson written on close.
- **Governance:**
  - The committee cannot decide until Risk has signed off.
  - The audit trail is append-only.
  - Memory is searchable with prefix matching.
  - Monitoring runs after every data refresh: health score, alerts, and a portfolio budget rule.
- **Findings the tool surfaced in testing:**
  - A USD 2.3 bn XLE line takes 4.8 days to build at 20% of daily volume.
  - Japanese bank ADRs would take 97 to 125 days, so they need Tokyo lines or an index.

### Deep research (built 16 Nov 2026; replaces the single-pass research step)

**Why it can beat ChatGPT or Claude deep research.** Those tools read the web and summarise it. They cannot compute
on CBUAE's own portfolio, test a claim against data, or remember what the committee decided last time. Nabd's
research **tests** each claim instead of describing it:

| | General web research | Nabd deep research |
|---|---|---|
| Evidence | Web pages | Open data run through models: event studies, regressions, analog periods, regime-conditioned returns, liquidity at reserve size; plus filings, central-bank statements, and Arabic and English news |
| Context | None | The SAA, the risk budget, the ideas already approved, and past decisions and lessons |
| Checking | Citations to pages | Every claim re-checked against its evidence; every number re-computed by a tool; unsupported claims removed |
| Balance | One narrative | A separate red-team pass writes the strongest case against |
| Output | A report | A verdict and confidence per hypothesis, the bear case, and triggers that feed the exit plan |
| Reproducible | No | Run ids, data as-of times, and the option to rerun "as of" a past date to see whether the method would have worked |
| Private | Cloud only | The same pipeline on Azure UAE North or an on-premise model |

**Pipeline (a background job: survives page reloads, resumes from checkpoints, notifies when done):**
1. **Plan.** Break the thesis into 4–6 testable hypotheses. Each names its test and its data, for example "BoJ
   normalisation widens bank margins: event study of bank returns around BoJ decisions, and sensitivity to JGB
   yields".
2. **Investigate.** One worker per hypothesis, up to 3 Codex sessions at once, each with 10–20 tool calls across
   quant and document tools. Findings stream onto hypothesis cards in the UI as they arrive.
3. **Challenge.** A red-team worker writes the bear case with its own evidence.
4. **Verify.** A checker goes claim by claim. Is the claim supported by its cited evidence? Does the figure
   recompute to the same value? Failing claims are dropped or flagged.
5. **Synthesise.** The report gives each hypothesis a verdict (supported, refuted or inconclusive) with a
   confidence level, plus the bear case, what would change the view, and proposed monitoring triggers. It includes
   charts built from the computed data.

**New tools:**
- **Event study:** returns around dated events, either central-bank decisions or news spikes detected in GDELT.
- **Conditional returns:** for example, how did the basket do when Brent rose 20% in 3 months, or in the stress
  regime?
- **Nearest-neighbour macro analogs.**
- **Rolling beta stability.**
- **Relative performance against the funding leg.**
- **Fundamentals history from EDGAR.**
- **Document search:** full-text search over 10-K risk factors and MD&A sections, and over Fed, ECB and BoJ
  statements.
- **Optional:** web search restricted to official sources.

**Runtime and controls:** about 8–15 minutes per idea, with caps on tool calls and minutes. Every step is logged
under the idea's audit trail.

**Measured on the Japanese banks idea (three runs while building):**

| | Run 1 | Run 3 |
|---|---|---|
| Claims removed by verification | 18 of 48 | 0 of 45 |
| Figures traced to cited evidence | 61% | 99% (154 of 156) |
| Official pages read and stored | 0 | 39 |
| Sources outside the allowlist | 1 | 0 |

Run 3 took 6.8 minutes and produced 167 evidence items.

**What made the difference:**
- **`read_page`.** Codex finds URLs with allowlisted web search (the domain list is enforced by Codex's own
  `allowed_domains`), then reads the page or PDF through Nabd. It gets back an evidence id to cite, and the full text
  is stored for the checker.
- **Auto-linking.** A claim that cites nothing is linked to a stored page containing its figures.
- **Document checks.** The checker reads the passages of central-bank documents that match the claim itself.

**Limits found:**
- **No Bank of Japan policy-rate series in open daily data.** The OECD series ended in 2023, so JGB-yield jumps
  stand in, and they are monthly.
- **IMF blocks automated fetching.**
- **As-of reruns cover prices, macro and documents only.** News and memory are not yet filtered by date.

### ML in the Investment module
- **Risk model:** EWMA and Ledoit-Wolf shrunk covariance on daily returns, plus rolling macro-factor betas. Drives
  tracking error, VaR, expected shortfall and marginal risk.
- **Regime model:** Gaussian hidden Markov model on market and macro series, giving risk-on and risk-off
  probabilities. Feeds the idea context, the stress weights and the monitoring.
- **Return-ranking model:** cross-sectional LightGBM on factors and regime, trained walk-forward. It reports its
  information coefficient and hit rate on screen, and is shown as one input, not an oracle.
- **Scenario engine:** historical replay, factor shocks with macro links from the Forecasting module, and
  block-bootstrap Monte Carlo.
- **News model:** GDELT tone and volume per name and theme. The LLM labels headlines by relevance and stance through
  structured output; the backend does the counting and the scores.
- **Model governance:** every model has a card (purpose, data, validation, limits), a version and a run log. This
  maps to CBUAE's Model Management Standards, for the Head of AI and the CRO.

### Memory and planning
- **Institutional memory** (SQLite with FTS5; local sentence embeddings optional). Every idea, parsed thesis,
  evidence snapshot, committee decision and rationale, exit and outcome is stored and immutable, with an audit log.
- **Retrieval:** Ask Nabd and the research step pull matching past records, for example "we looked at Japanese banks
  in March; MRMC deferred it on tracking error".
- **Learning loop:** when an idea closes, Nabd compares the outcome with the thesis and writes a lesson. It also
  tracks how well the screening model's ranks did, so its displayed hit rate stays honest.
- **Planning:** the research step and Ask Nabd use the plan → execute tools → answer loop (section 5). The plan is
  shown to the user as it streams, so they see what Nabd is about to check before it answers.
- **Conversation memory:** each user's thread keeps context such as "the idea we discussed" and "those three names".

---

## 5. Ask Nabd: Codex with figures the LLM cannot invent

**Updated in phase 0.** Codex CLI 0.166 supports real tool calling through the app-server's experimental
`dynamicTools`. Nabd registers its own Python functions as tools, Codex calls them (`item/tool/call`), and the
backend runs them and returns the results. The three-step plan → execute → answer workaround is no longer needed.

How Ask Nabd works:
- **Tools only.** Every figure comes from a tool: series queries, model runs, portfolio and risk views, scenarios,
  news search, chart building, and a calculator.
- **No arithmetic in the model.** The smoke test showed the model will subtract two figures itself (285 − 231) if
  allowed, so a `calc` tool and an instruction forbid it.
- **Locked down.** Shell, file edits, web search, apps, plugins and the user's personal MCP servers are all
  switched off; the sandbox is read-only with no network. The `code_mode_host` feature has to stay on, because it
  hosts the dynamic tools.
- **Structured final answer.** It comes back through `outputSchema`: `{text, charts: [vega-lite spec referencing
  data ids], citations}`. The backend inserts the data into the charts.
- **Model.** Defaults to the signed-in account's default model (`model/list`). The personal profile's model may not
  be available to the ChatGPT sign-in.

Streamed as SSE events: `tool.start`, `tool.result`, `text.delta`, `chart`, `citations`, `done`. This was verified
end to end in phase 0, from the browser through FastAPI to Codex and back.

**Important for CBUAE:** Codex OAuth uses your ChatGPT login and sends prompts to OpenAI. That is fine for a demo on
your laptop with open data, but not for CBUAE data or the on-premise pitch. The gateway therefore has a provider
switch: `codex` for development and demos, `azure_openai` (UAE North) and `local` (open-weight model on premise) for
the client environment. Also check that using ChatGPT-plan tokens for a client demo is acceptable under OpenAI's terms.

---

### Built in phase 3 (16 Nov 2026)
- **A sheet on every page.** "Ask Nabd" sits in the floating tab bar (or press `/`). It knows the current page and
  the selected idea, and threads persist across questions.
- **Answers come only from tools.** Codex uses 30 Nabd tools (data, models, ideas, stress, documents, official
  pages, `calc` for arithmetic). Each step streams to the sheet, then the answer text streams in.
- **Charts are built from tool data.** The model chooses only which evidence to plot. The backend draws from the
  tool's own numbers: at most 4 series, one axis, a palette validated for colour vision (bronze, blue, magenta,
  teal), direct labels, a crosshair tooltip and a table view.
- **Figure check.** Every figure in an answer is traced to the evidence cited in the same paragraph, and the badge
  shows the count, for example "8 of 8 figures traced".
- **Tested questions:**
  - Hormuz stress on the whole portfolio: bar chart, 6 of 6 traced.
  - Brent against XLE and SPY over one year: line chart, 8 of 8 traced.
  - The follow-up "and over three years?", answered from the conversation: 7 of 7 traced.

### Built in phase 4 (16 Nov 2026)
**Target.** No open API carries UAE quarterly GDP: FCSC blocks automated access, the IMF has no UAE quarterly
national accounts, and the World Bank is annual only. So the target is a **release record**
(`data/manual/fcsc_quarterly_gdp.csv`).
- It holds 13 quarters of first-release real and non-oil growth, Q4 2021 to Q2 2026, each with its release date and
  official source (FCSC through WAM, Ministry of Economy, CBUAE Quarterly Economic Review).
- Missing quarters are left blank with reasons; nothing is inferred.
- Three later-vintage 2022 values are used for training only, never scored.
- An analyst can replace the record with the full FCSC download.

**Indicators.** Inputs are monthly, each with its publication lag:
- IMF PortWatch: daily Strait of Hormuz transits, and UAE port calls, imports and exports.
- Brent, UAE equities, the VIX, US yields and the dollar.
- GDELT news tone and volume. Its history since 2019 comes from a weekly sample of the raw files and was still
  downloading at the end of this phase.

**Models.**
- A dynamic factor model on real-activity inputs only. With rates and the dollar included, the factor tracked the
  global financial cycle and missed the 2026 collapse.
- MIDAS on that factor.
- A ridge bridge regression.
- A news model.
- An ensemble.
- The last release as the benchmark.
- No boosted trees, because about 16 target points are too few.

**Pseudo real-time backtest.** Scored on first releases, each quarter at three points (mid-quarter, quarter end, a
month after):

| Target | Champion | Error (RMSE) | Against the benchmark |
|---|---|---|---|
| Non-oil GDP | Bridge | 1.81 pts | −33% |
| Real GDP | Bridge | 1.29 pts | −45% |

**The shock test (Q2 2026).**
- From April to July, every model called a contraction (about −5% to −6.5%) while the benchmark said +6.1%.
- When Q1 2026 (+4.8%) was published on 4 August, the models re-estimated the link to GDP and moved to +0.6%.
- The official figure was −1.1%, published on 9 October.

**Page.**
- Weekly nowcast paths for the test quarter and for the open and current quarters, with 70% bands taken from past
  errors.
- A model leaderboard by horizon, what moved the nowcast in the last 4 weeks, the inputs table, and a Hormuz and
  Brent scenario.
- Runs repeat after each shipping refresh, and Ask Nabd has a `nowcast` tool.

### Built in phase 5 (16 Nov 2026)
**Data.** AMLSim needs a Maven toolchain, so Nabd generates **AMLSim-style** data in Python. Real AMLSim output or
CBUAE data can replace these files.
- 6,000 accounts across six banks and about 90,800 instant payments over 14 days.
- 26 labelled rings across seven typologies: fan-in, fan-out, cycle, scatter-gather, gather-scatter, stacked
  layering, and a 40-account mule ring spanning all six banks.
- 24 legitimate look-alikes (payroll processors, exchange houses, busy merchants) that simple rules flag wrongly.

**Methods**, scored against the labels:

| Method | Cases to open | Rings caught whole (of 26) | Precision | Recall |
|---|---|---|---|---|
| Rules | 350 | 0 | 0.26 | 0.29 |
| **Money trail** | 36 | 18 | 0.83 | 0.80 |
| Communities | 8 | 8 | 0.55 | 0.33 |
| Cycles | 7 | 5 | 0.76 | 0.09 |
| ML on features (cross-fitted by ring) | 57 | 17 | 0.79 | 0.74 |
| **Combined** | 32 | 15 | 0.91 | 0.70 |

**What made the money trail work:**
- A pass-through means the money received equals the money sent within the hold window, counting split
  forwarding as a whole.
- Groups join only through **mules** (accounts that forward most of what they receive) or accounts dedicated to
  mule flows. Before this, ordinary accounts fused 15 rings into one 150-account case.

**Page.**
- A headline comparison of rules against the network methods.
- A canvas network with pan, zoom and hover, plus a method switch.
- Cases in plain numbers. Opening a case shows money in, money moved inside and money out, a timeline of how it
  moved, and the accounts.
- Labels shown on demand, and settings for the hold window and pass-through share.
- Ask Nabd has a `fraud_summary` tool.

### Built in phase 6 (16 Nov 2026)
**One alert store for all modules** (`app/monitoring/alerts.py`).
- Alerts are deduplicated while open and resolve themselves when the condition clears.
- They can be acknowledged ("seen by"), link to where they are acted on, and stream to every page.

**Rules** (`app/monitoring/rules.py`, plus the investment monitor):

| Area | Rule |
|---|---|
| Data | Feeds late or never downloaded. A failed refresh with current cached data no longer counts as failing, which removed a false alarm on 57 price series |
| Models | VaR backtest above its limit; market regime in stress; ranking-model IC drifting negative; nowcast champion changed |
| Forecasting | Nowcast moved 0.75 points or more; contraction signalled; new FCSC release |
| Fraud | New high-risk networks (combined score 0.9 or above) |
| Investment | Stop, target, review date, invalidation triggers, news tone, risk budget |

**When rules run.** After every data refresh, idea change and model run (nowcast, fraud, ranker), and at least every
15 minutes. Fraud detection runs daily, and the nowcast reruns after each shipping refresh.

**Overview.**
- Four tiles, one number each.
- A "Needs attention" inbox with Open and Acknowledge.
- The model registry with live OK, Watch or Breach status and full cards, mapped to the Model Management Standards.
- An audit log of decisions, runs, alerts and acknowledgements.
- The technical system view moved behind "System status".

**Tested live.** A detection run with a 2-hour window raised "5 new high-risk payment networks" on the open
Overview without a reload. Acknowledging it was recorded in the audit log.

### Built in phase 7 (16 Nov 2026)
**One command from a fresh clone.** `make demo` installs, runs `doctor`, seeds and starts both servers.
- `nabd seed` brings an empty data folder to a working demo in about 3 minutes: prices, FRED, PortWatch, central-bank
  releases, the latest news, then the ranker, fraud detection, the nowcast and a monitoring check. Each step prints
  its time and result; a partial failure names the series and the reason. `--full` adds the news history.
- Tested from an empty folder: 9 of 9 steps succeeded. The GDP release record now ships with the code
  (`app/ml/forecasting/seed/`) and is copied into `data/manual/` on first run.
- `scripts/dev.sh` (`make dev`) starts the API and the web app together; Ctrl+C stops both, tested with no leftover
  processes.

**Security fixes from a review of the code.**
- The price-panel query is parameterised (a crafted symbol could have reached DuckDB SQL).
- Basket symbols must be in Nabd's universe and appear once.
- Page fetching for research refuses private and local addresses and checks every redirect against the allowlist.

**Failure states.** An error boundary around each page (Nabd keeps running; reload the page), a banner when the
Investment page cannot load, and data sources that wait when rate-limited: IMF PortWatch shares one quota across all
its users and was refusing requests during testing, so the connector now waits as asked and refreshes only recent
days.

**Tests.** 49 backend tests, 16 of them new HTTP-level tests: validation (short ideas, unknown or duplicate symbols,
cuts larger than the holding, zero weights), stages run out of order (409), unknown records (404), soft delete, and
the monitoring endpoints. They found a real bug: the audit log failed on a fresh install before any idea existed.

**Docs.** `nabd/README.md` (setup, architecture, data sources, LLM provider, security notes, limits) and
`docs/DEMO.md` (a 15-minute walkthrough with what each audience should take away, likely questions with honest
answers, and what to do when something fails).

### After phase 7 (17 Nov 2026): Overview is markets and news only
The teams do not want a page about data feeds, model status or system health. The Overview now shows only:
- **Markets.** 18 levels from Yahoo's chart endpoint, kept apart from the investable universe and refreshed every
  15 minutes: DFM General, FTSE ADX General, Tadawul, S&P 500, Nasdaq, Euro Stoxx 50, FTSE 100, Nikkei, Hang Seng,
  US 10-year and 3-month yields, Brent, gold, US gas, the dollar index, EUR/USD, USD/JPY and the VIX. Each has
  today's move (basis points for yields), a 3-month sparkline, and on selection a chart with 1-month and
  year-to-date moves. Yahoo serves only the current level of the Gulf indices, so their day move comes from the
  quote's previous close and their history builds from Nabd's daily refreshes. Below: the biggest one-day moves
  among Nabd's 160 instruments.
- **News.** Headlines from the GDELT ingest, shown only when the title is about the topic (GDELT's own theme codes
  tag many articles that merely mention it), with press-release wires dropped and one headline per syndicated
  story. Topics: markets (a new theme), oil, Gulf shipping, UAE economy, Fed and rates, gold, AI and chips, and
  central-bank releases (Fed, ECB, BoJ, BIS).

The alert rules, model registry and audit log still run in the backend (`/api/monitor/*`); investment alerts show
on the Investment page.

### After phase 7 (17 Nov 2026): bearish ideas, a live fraud network, phone layouts
**Bearish ideas can now be expressed properly** (the AI idea could only cut whole mandates before).
- *Underweight a single name.* A reserve does not short, but it holds NVIDIA and Microsoft through ESGU and ESGD, so
  holding less than the benchmark is an ordinary active underweight. The cap is what is held directly plus through
  the mandates (mandate weight × the company's weight in the fund), enforced at the API and when a basket is resized.
  The fund weights come from the official iShares holdings files, which an analyst saves to `data/manual/`; iShares
  serves them only through its website, so Nabd does not fetch them.
- *Research only.* Any name can go to deep research without being traded; the risk model, stress and monitoring
  ignore it, and deep research is told which names are traded.
- *Protect* always includes defensive equities and gold next to Treasuries, at most four of each type. For the AI
  basket, defensive equities rose about 1% on its worst days; gold fell 0.7%.
- *Cut proceeds* go to T-bills or stay in the equity mandates.

**Screening is now "What to look at".** Codex reads the idea and names its driver (what it is really a bet on,
measured by real instruments) and proposes 6-14 candidates across equities, bonds and gold, grouped as Hold less of /
Add as protection / Buy / Study first, each with a one-line reason. Nabd keeps only instruments it has and measures
every candidate: how it moves with the driver, what it did on the driver's worst days, what we hold, the risk it
adds. A "Data agrees / Data disagrees" badge shows where the evidence contradicts the suggestion (for the AI idea,
gold: it fell on AI stocks' worst days). It runs right after the thesis (about 25 seconds); the rule-based screen
stands in, labelled, if Codex is unavailable.

**Whole fraud network.** A live force simulation (d3-force 3.0.0, its dependencies held at their 2021 releases) on
canvas, full width: rings pull into knots, accounts can be dragged and pinned, scroll zooms, hover shows who paid
whom with arrows, search finds an account, click selects its case in a floating card, colour by risk or bank, and a
filter for flagged accounts and their counterparts.

**Case money flow** (Fraud page default): entry → pass-through layers → exit, arrows sized by amount, a replay of the
transfers in time order, linked hover with the timeline; top to bottom on phones.

**Charts and phones.** The shared line chart now always contains its data, trims empty weeks and sizes its labels;
Forecasting compares the champion and the benchmark; every page fits a 375 px phone.

### Next: a lighter investment screen (planned, not built)
Feedback on 17 Nov: the investment screens show too much at once. Proposed, in order:
1. **One decision per screen.** Each stage opens on a two-line summary and one action ("Nabd suggests holding 1%
   less of US equities; the data agrees"); details (factor tables, liquidity, ML rank) sit behind "Show detail".
2. **Three facts per suggestion, not six:** how it moves with the driver, what it did on the bad days, the risk it
   adds. Correlation, volatility and liquidity move into the detail view.
3. **Committee pack as a one-page brief** with the full pack as an attachment, rather than every section inline.
4. **Plain-language labels throughout** (no "TE", "beta", "SAA" without a gloss), as done for screening.
5. **Progressive stepper:** later stages stay collapsed until the earlier one is done, so a new idea shows one
   panel, not seven.
Measure: a new team member can take an idea to the committee without help, and each screen fits a laptop without
scrolling.

### Added 17 Nov: review before research, and a proposed split
- *Review before research.* "Review and start research" first shows what is traded, what is research-only, the
  portfolio by asset class now and after, exposure to the idea's driver now and after, and the risk budget used.
  It warns when a selection does not do what the idea says (for the AI idea, a gold-only basket left AI exposure
  unchanged, so stress tested gold, not equities).
- *Proposed split.* Deep research now ends with a size for each selected name (research-only names included).
  Nabd enforces the limits (selected names only, cuts within holdings) and recomputes the portfolio and budget;
  "Use this split" adopts it and reruns portfolio fit, clearing stale stress and committee results.
- The SRI warning now applies to equities only (gold and bonds are outside SRI screening).

### Added 17 Nov: a Kalman nowcast, and what AI adds to it

CBUAE already forecasts GDP, so the question for the demo is what AI adds. The Forecasting page now shows one model,
Kalman, with and without AI news, against the IMF World Economic Outlook. The old models (factor bridge, MIDAS, ridge
bridge, GDELT news regression, ensemble), the leaderboard and the 54-minute run are gone; the whole run takes about
12 seconds. Pieces:

- **Kalman state-space nowcast** (`ml/forecasting/kalman.py`): a dynamic factor model with quarterly GDP inside the
  state, run through the Kalman filter and smoother. Mixed frequency and the ragged edge are handled in one pass;
  GDP's own persistent component carries the last releases forward; GDP's weights on the factors are kept at zero
  or above (an economic sign restriction: before 2026 the sample has no recession to pin the sign down). Two-step
  estimation (Doz, Giannone and Reichlin), so a nowcast takes about 0.1 s and the backtest refits at every date.
  The nowcast splits exactly into one contribution per input, and a revision into each input's new data plus
  re-estimation.
- **AI news signal** (`ml/forecasting/ai_news.py`): UAE business headlines from a fixed sample of GDELT GKG files
  (16 per month since 2020) and the live feed, labelled by the LLM for relevance, sector and direction (-2 to +2).
  Labelling is blind to dates: headlines from different months are shuffled together without dates or sources.
  Daily averages become two monthly indicators, non-oil and oil, published with a one-day lag.
- **Nowcast run** (`ml/forecasting/ai_eval.py`): hard data only, plus AI news (and GDELT tone, scored but not shown); scored in pseudo real
  time against first releases at three points per quarter, with coverage of the model's own 70% and 90% bands, and
  with and without the Q2 2026 contraction.

The page shows the next two quarters with and without AI, the track record and forecast to the end of next year on
one chart, full-year real GDP against the IMF (with what the unpublished quarters would need to average for the IMF to
be right), an exact "why it moved" breakdown, the AI signal by month, and every headline the AI read with its label.
IMF figures come from `data/manual/imf_weo_uae.csv` (the IMF site blocks automated access; one row per vintage).

### Added 17 Nov: the fraud page is one investigation

Three areas only: a four-number summary, one large network, and an AI investigation panel. Two approaches are kept:
the gradient-boosted account score (scikit-learn histogram gradient boosting, the XGBoost family, cross-fitted by
ring) and graph detection (money trail plus cycles, kept where the score agrees). The rules, community and cycle-only
methods still run inside `detect.py` as building blocks and benchmarks but are off the page; so are the run settings
and the 900-node whole-network layout.

- **Fraud rings view** (`components/FraudGraph.tsx`, SVG with d3-force): every detected network is a bubble; the open
  one shows its accounts (colour = ML risk, ring = where money enters or leaves) and numbered arrows in time order,
  with the outside money in and out. Click an account to trace money onward (orange) and back (blue); drag to move;
  a day slider replays the network's growth.
- **Money flow view** (`CaseFlow`, now with one row per bank): left to right in time, so a cross-bank hop is a move
  between rows (after arXiv:2605.10522's tabular sequential layout).
- **Pattern** of each network (circular flow, layering chain, fan-in, fan-out, scatter-gather, gather-scatter) is read
  from the direction of its transfers (`run.pattern`), never from the labels.
- **AI investigation** (`ml/fraud/explain.py`): Codex writes a note from the network's accounts, transfers, outside
  flows, hold times and ML scores, without the labels; every cited transfer is checked against the data and dropped if
  it does not match. Notes are cached per run; the top network's note loads with the page; an account note on request.

### Added 17 Nov: answers for economists, the CRO and the investment team

- **Test the nowcast** (`ml/forecasting/explore.py`, Forecasting drawer): switch inputs on and off and re-run the
  same pseudo real-time backtest (about 3 seconds); upload CBUAE's own past nowcasts (template provided) to score
  them next to Kalman + AI news and the average of the two.
- **Governance page** (`monitoring/governance.py`): model inventory with status and live evidence; a validation pack
  per model generated from its card and recorded runs (purpose to sign-off; not a validation); AI evaluation from the
  checks every run already makes; human 👍/👎 review on research, fraud notes and Ask Nabd answers; a blind
  headline-labelling screen that measures the AI's news labels against analysts (agreement and kappa).
- **Fraud data safety**: *What the AI saw* shows the exact input of a note and what is never sent; a short panel on
  how real payment data would stay inside CBUAE.
- **Commodities, gold and bonds**: the investment universe (`universe.INVESTABLE_ASSETS`) and the notional SAA
  (money market 25%, bonds 65%, gold 4%, commodities 6%). Equities stay as data for the nowcast and markets but are
  never proposed or traded; the risk sleeve that funds tilts is gold plus commodities.

## 6. Monitoring and alerts

Async loops in the FastAPI lifespan (TradingMaus pattern) or APScheduler:
- **Data:** refresh each source on its cadence (prices 15 min, GDELT hourly, PortWatch daily, macro daily or monthly);
  mark feeds late when they miss their window.
- **Rules:** nowcast moved more than x pp; model error drift; challenger beating champion for n weeks; news-tone spike;
  price or drawdown beyond limits; risk-budget use above threshold; new fraud trail above score.
- Alerts are stored, deduplicated, acknowledged, and streamed to every open page; the Overview page is their inbox.

---

## 7. Phases (about 4 weeks for one engineer with Claude)

| Phase | Days | Delivers | Done when |
|---|---|---|---|
| 0. Skeleton | 2 | Monorepo, FastAPI + Vite apps, Codex session ported, `doctor` command, SSE channel, design ported to React | Frontend shows the 4 pages; backend streams a heartbeat; Codex answers a test prompt |
| 1. Market data | 2 | Prices (Yahoo, Stooq), FRED, GDELT, EDGAR connectors, cache, catalog | Universe prices and macro refresh and show freshness |
| 2. Investment flow | 6 | Idea parsing, screening, research note, risk model, portfolio fit, stress, committee pack, exit triggers, memory, monitoring | One idea goes from free text to committee to monitored position, streamed, with every number tied to a run |
| 3. Ask Nabd | 2 | Plan, execute, answer with Vega-Lite charts and citations; conversation memory | Questions produce streamed answers with computed charts |
| 4. Forecasting | 4 | FCSC, PortWatch, DLD and CBUAE connectors; 5 models; backtest; streamed runs | "Run backtest" streams and updates charts; errors versus benchmarks shown |
| 5. Fraud | 3 | AMLSim data, 5 methods, evaluation, sigma.js network, streamed runs | Methods compared against labels on screen |
| 6. Monitoring | 2 | Scheduler, alert rules across modules, Overview inbox, audit log, model registry view | Alerts appear live when data, models or triggers change |
| 7. Hardening | 2 | Tests, demo script, failure states, README | Clean `make demo` from a fresh clone |

---

## 8. Decisions (agreed 16 Nov 2026)

1. **LLM:** Codex OAuth for the demo; provider switch for Azure OpenAI UAE North or an on-premise model.
2. **Fraud data:** AMLSim generated locally.
3. **Frontend:** React + Vite + TypeScript.
4. **Storage:** SQLite + DuckDB.
5. **Where:** `nabd/` in this project.
6. **Order:** Investment first, then Ask Nabd, Forecasting and Fraud.

## 9. Risks

- Payment data is not public, so the payment-driven nowcast is synthetic until the on-premise POC.
- FCSC's ongoing GDP revision limits the backtest history; we label vintages carefully.
- Codex app-server's protocol is unstable (TradingMaus pins CLI ~0.161); pin the version and keep the gateway thin.
- Yahoo data is unofficial and delayed; fine for a POC, replace with a licensed feed for production.
- Codex OAuth sends data to OpenAI: demo-only, never with CBUAE data.
