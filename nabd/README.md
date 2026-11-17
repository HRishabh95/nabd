# Nabd

A working proof of concept for the Central Bank of the UAE: an investment desk, a GDP nowcast and a fraud-network
detector, on open data, with an assistant ("Ask Nabd") whose every figure comes from a model run, not from the LLM.

- **Overview.** What markets are doing (UAE and Gulf indices, global equities, rates, commodities, FX) and the
  news that matters, filtered to headlines actually about each topic, plus central-bank releases.
- **Investment.** A free-text idea goes through screening, deep research, portfolio fit, stress tests, a committee
  pack with exit triggers, and live monitoring.
- **Forecasting.** UAE non-oil and real GDP nowcasts from shipping, markets and news, scored in a pseudo
  real-time backtest against the official first releases. A Kalman state-space model is run with and without
  news read by an LLM, to show what AI adds to a GDP forecast a central bank already has.
- **Fraud network.** Mule and laundering rings found by following the money across banks, compared with simple
  rules on labelled synthetic payments.

The design, data choices and measured results are in [`docs/PLAN.md`](../docs/PLAN.md). The demo walkthrough is in
[`docs/DEMO.md`](../docs/DEMO.md).

## Run it

You need Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 20+, and the
[Codex CLI](https://github.com/openai/codex) signed in with a ChatGPT account (`codex login`).

```bash
cd nabd
cp .env.example .env    # optional: every setting has a default
make demo               # install, check, seed open data and models (~3 min), start both servers
```

Then open <http://localhost:5173>. The AI news signal in the GDP nowcast is not part of `make seed` (it downloads about
7 GB of GDELT files and makes about 40 LLM calls): to add it, open Forecasting and press **Update AI news** once. Without
it the nowcast runs on hard data only. On a Mac, `make` comes with Xcode: if it stops with "You have not agreed to the
Xcode license agreements", run `sudo xcodebuild -license` once, or run the commands in the `Makefile` by hand.

`make demo` runs these steps, which you can also run on their own:

| Command | What it does |
|---|---|
| `make setup` | Installs the backend (`uv sync`) and frontend (`npm install`) dependencies |
| `make doctor` | Checks Python, the database, the Codex sign-in and optional keys; says how to fix each failure |
| `make seed` | Downloads open data and runs every model once. Safe to rerun: fresh data is skipped |
| `make seed-full` | Adds 30 days of news and the weekly news history since 2019 (about 1 GB, 30+ minutes). The news model and the backtest figures in `docs/PLAN.md` need it |
| `make dev` | Starts the API (127.0.0.1:8000) and the web app (localhost:5173); Ctrl+C stops both |
| `make test` | Backend tests, lint and the frontend type check |

Once running, the API refreshes each source on its cadence (market levels every 15 minutes, prices every 30, news every 15, macro and
central-bank releases every 6 hours, shipping every 12), reruns the models when their inputs change, and checks the
alert rules after every refresh and at least every 15 minutes. Set `NABD_REFRESH_ENABLED=false` to freeze the data
for a rehearsed demo.

## How it is built

```
nabd/
  backend/   FastAPI · SQLite (WAL) for state, DuckDB over parquet for series · scikit-learn, statsmodels, hmmlearn, networkx
    app/api/          HTTP routes, one file per module, plus /api/stream (server-sent events)
    app/data/         connectors (Yahoo, FRED, GDELT, IMF PortWatch, central banks, SEC), series store with vintages, scheduler
    app/invest/       idea flow, screening, deep research, verification, monitoring
    app/ml/           portfolio risk, regime, ranker, stress · forecasting · fraud · model registry
    app/agents/       Ask Nabd: tools, charts, figure check, threads
    app/llm/          the Codex app-server session and a provider gateway
    app/monitoring/   one alert store and the rules for every module
  frontend/  React + Vite + TypeScript, no UI framework; Apple HIG "Liquid Glass" styling
  data/      created on first run; never committed
```

- **Streaming.** Every long job (refreshes, research, model runs) publishes typed events to one SSE channel. A page
  that reconnects replays what it missed, and falls back to polling if the stream stalls.
- **The LLM never produces a number.** Codex calls Nabd's own Python tools (`dynamicTools`), structured output
  is enforced with JSON schemas, and every figure in an answer or research note is traced to a tool result. Figures
  that cannot be traced are flagged or removed.
- **Vintages.** Each data point records when Nabd first saw it, so backtests and as-of research reruns use only what
  was knowable on the date.

## Data sources

All open, no accounts. Each is cited where it is used.

| Source | Used for | Notes |
|---|---|---|
| Yahoo Finance chart endpoint | 10 years of daily prices, 160 instruments; 18 index, rate, commodity and FX levels for the Overview | Unofficial; replace with a licensed feed in production. No single ADX stocks, and only the current level of the DFM, ADX and Tadawul indices |
| FRED public CSV | Rates, oil, dollar, spreads; optional global-economy inputs for the nowcast (US industrial production, WTI, copper, European gas, policy uncertainty) | No key needed |
| GDELT GKG 2.1 raw files | News volume and tone by theme, English and Arabic (translated) | The GDELT search API rate-limits shared networks, so Nabd reads the 15-minute files |
| GDELT GKG 2.1 sample + Codex | AI news signal for the nowcast: UAE business headlines (16 sampled 15-minute files a month since 2020, plus the live feed), each labelled by the LLM for relevance, sector and direction, in shuffled batches without dates | Headlines are a sample of GDELT's English feed; labels are stored with the model that made them |
| IMF PortWatch | Hormuz transits, UAE port calls and trade | Shared rate limit; Nabd waits when asked and refreshes only recent days |
| Fed, ECB, BoJ, BIS feeds | Central-bank releases for research and Ask Nabd | Full text is fetched only from official domains |
| SEC EDGAR | Filings and reported fundamentals | Off until you set `NABD_SEC_USER_AGENT` (SEC requires a contact) |
| FCSC first releases | The GDP target | FCSC blocks automated access, so the release record is a CSV with sources (`app/ml/forecasting/seed/`, copied to `data/manual/`) |
| IMF World Economic Outlook | The IMF comparison on Forecasting | The IMF site blocks automated access: `imf_weo_uae.csv`, one row per vintage with its source |
| AMLSim-style generator | Payments with labelled laundering rings | Synthetic; real AMLSim output or CBUAE data can replace it |

Sites that put up bot checks (Stooq) or refuse automated access (FCSC) are respected, not worked around.

## For contributors and Claude Code

Rules for what may be downloaded, what must stay manual, what the LLM may see and what may be committed are in
[`CLAUDE.md`](../CLAUDE.md) at the repository root; Claude Code reads it automatically. In short:

- Use only the sources above, through Nabd's connectors, and respect their rate limits.
- Never scrape or work around sites that block automated access (FCSC, the IMF site, iShares, Stooq); their figures
  are hand-maintained CSVs with a source per row. Never invent a figure.
- Ask before slow or large jobs: `make seed-full`, **Update AI news**, deep research.
- Prompts go to OpenAI through Codex in this demo: open or synthetic data only.
- Never commit `.env` or `nabd/data/`; run `make test` before pushing.

## LLM provider

`NABD_LLM_PROVIDER=codex` uses the Codex CLI's app-server with your ChatGPT sign-in. It is for the demo only:
**prompts go to OpenAI**, so use open data only and never CBUAE data. Inside Nabd, Codex has no shell, no file
edits, no plugins or MCP servers, a read-only sandbox with no network, and web search only where a step allows it
(official domains for deep research). The gateway (`app/llm/gateway.py`) is the one place to add Azure OpenAI
(UAE North) or an on-premise model for the client environment.

## Security notes for this POC

- **Local only.** The API binds to 127.0.0.1 and accepts browser requests only from the local web app (CORS). There
  is no sign-in: every action is recorded as "Investment team". Roles and sign-in come with the client environment.
- **Inputs are validated** at the API: idea text length, basket symbols must be in Nabd's universe, a cut cannot
  exceed the holding, stages must run in order. Database queries are parameterised.
- **Fetching pages.** Research reads full text only from an allowlist of official domains, refuses private and
  local addresses, and checks every redirect.
- **Secrets.** `.env` and `data/` are ignored by git. Nabd never fills in a contact or key for you.

## Limits

- Prices are unofficial and delayed; fraud data is synthetic; the GDP target has about 16 quarters, so nowcast bands
  are wide.
- The models are at the development stage. None has been through independent validation under the Model
  Management Standards.
- Single user, single machine, no sign-in.
