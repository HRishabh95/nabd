# Working on Nabd with Claude Code

Nabd is a proof of concept for the Central Bank of the UAE: an investment desk (commodity book), a GDP nowcast, a
fraud-network page, a Governance page and Ask Nabd. The app lives in `nabd/` (FastAPI backend, React frontend);
`docs/PLAN.md` explains the design and `docs/DEMO.md` the demo. Read `nabd/README.md` before changing anything.

## Rules for data: what to download, and what not to

**Allowed sources** (open, no account). Use only these, through the connectors in `nabd/backend/app/data/connectors/`:

| Source | How Nabd gets it | Limits to respect |
|---|---|---|
| FRED (St. Louis Fed) | public `fredgraph.csv`, no key | none in practice; series list in `app/data/universe.py` |
| IMF PortWatch | ArcGIS API | shared quota: on HTTP 429, wait as told (the connector does); refresh only recent days |
| Yahoo Finance | chart endpoint | unofficial and delayed; never present it as an official price |
| GDELT GKG 2.1 bulk files | `data.gdeltproject.org` 15-minute files | use the bulk files, **not** the GDELT search API (it returns 429 on shared networks) |
| Fed, ECB, BoJ, BIS | official feeds and pages | full text only from official domains (`_safe_host` guard) |
| SEC EDGAR | API | only with `NABD_SEC_USER_AGENT` set; respect SEC's fair-access limits |

**Never work around a site that blocks automated access.** FCSC, the IMF website and iShares refuse automated
downloads, and Stooq shows a bot check. Do not scrape them, change user agents, use headless browsers or proxies.
Their data enters as hand-maintained CSVs with a source for every row:

- `nabd/backend/app/ml/forecasting/seed/fcsc_quarterly_gdp.csv` (and `_later_vintage.csv`): FCSC GDP first releases
- `nabd/backend/app/ml/forecasting/seed/imf_weo_uae.csv`: IMF World Economic Outlook projections
- On first run these are copied to `nabd/data/manual/`; an analyst updates them there. Add a row per new release, with
  its release date and source URL. Do not invent or estimate figures.

**Large or slow downloads need the user's OK first:**
- `make seed-full` (about 1 GB of GDELT history, 30+ minutes)
- Forecasting → **Update AI news** (about 1,300 GDELT files, roughly 7 GB downloaded and discarded, plus about 40 LLM calls)
- Deep research (5 to 12 minutes and dozens of LLM calls per idea)

## Rules for the LLM

- The demo LLM provider is Codex, which sends prompts to OpenAI. **Use only open or synthetic data in prompts.**
  Never put CBUAE data, personal data, credentials or the user's details into a prompt, a URL or a request header.
- The LLM never supplies a figure: figures come from tools and are traced or checked (see `app/agents/ask.py`,
  `app/invest/deep.py`, `app/ml/fraud/explain.py`). Keep it that way when adding features.
- LLM calls cost money and time; do not run research, relabelling or bulk AI jobs unless the user asks.

## Rules for the repository

- Never commit `.env`, anything in `nabd/data/` (database, downloaded series, manual files), `node_modules`, `.venv`
  or build output; `.gitignore` covers them. `.env.example` holds placeholders only.
- Commit or push only when the user asks.
- Before saying a change works: `cd nabd && make test` (backend tests, lint, frontend type check), and for UI changes
  look at the page in the browser at desktop and phone widths.
- The fraud data is synthetic (AMLSim-style); label it so in any UI or document.

## Getting a working copy

```bash
cd nabd
cp .env.example .env        # optional
make demo                   # install, check, seed open data and models, start the API and the web app
```

Then, if you want the AI news signal in the GDP nowcast (optional, slow, needs Codex): Forecasting → Update AI news.
Without it the nowcast runs on hard data only and the AI-news lines and figures are absent.
