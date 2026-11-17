# Nabd demo: 15 minutes

For the Investment team, the Head of AI, the Head of Cyber and the CRO. One presenter drives; the script is in
the order of the dock (Overview, Investment, Forecasting, Fraud network) with Ask Nabd in the middle.

Figures below are from the demo data on 16 Nov 2026. They change as data refreshes; say what the screen says.

## Before the room fills (10 minutes)

1. `make doctor`: every line green. If Codex is not signed in, run `codex login`.
2. Freeze the data so nothing moves mid-demo: set `NABD_REFRESH_ENABLED=false` in `nabd/.env`, then `make dev`.
3. Open <http://localhost:5173> in a browser window about 1440 px wide. Close other tabs.
4. Ask Nabd one warm-up question (below) so the Codex session is already started.
5. Have the three ideas ready on the Investment page: *Quality energy producers* (monitored position),
   *Japanese banks* (at committee) and *Reduce AI-linked equity risk* (at screening).

**If Codex is unavailable**, everything except new research and Ask Nabd still works: screening, portfolio fit,
stress, committee packs, monitoring, the nowcast and fraud detection are all Python models. Say so and carry on.

## The walkthrough

### 0:00 Overview: what markets are doing and the news (1 min)

- One line under the title says the day: DFM, S&P 500, Brent, the US 10-year and gold.
- **Markets**: UAE and Gulf indices, global equities, rates, commodities, currencies and the VIX, each with today's
  move. Select one for its chart (1 month, 3 months, 1 year), its 1-month and this-year moves.
- **News**: headlines that are actually about oil, Gulf shipping, the UAE economy, the Fed, gold, AI and markets,
  one per story, plus the latest Fed, ECB and BoJ releases. Arabic sources are included.
- *Caveat:* prices are Yahoo's and may be delayed; DFM, ADX and Tadawul history builds up from the first download,
  because Yahoo publishes only their current level.

### 1:00 Investment: from an idea to a monitored position (5½ min)

**The portfolio view.** A notional USD 285 bn reserve with an equity sleeve and a 60 bp active-risk budget. Show the
ideas tested so far and what each added to risk.

**Start an idea live** (optional, 30 seconds): type "AI capex slows and semiconductors sell off" and choose
*tactical*. Codex turns it into a thesis with assumptions; screening then shows the names we hold that are most
exposed (the *Reduce* list) and what would protect the portfolio. Leave it running and move on.

**Open Reduce AI-linked equity risk (at screening)** to show how Nabd turns an idea into things to look at.
- *What to look at*: Nabd reads the idea as a bet on "AI-linked equities" and shows that about 5% of the portfolio
  moves like them today.
- *Hold less of*: the US equity mandate, which the data confirms falls when AI stocks fall.
- *Add as protection*: Treasuries (the data agrees) and gold, which the data flags: it fell on AI stocks' worst
  days too. Point at that badge: the assistant suggests, the models check.
- *Study first*: NVIDIA, Broadcom, Microsoft and the others, sent to deep research without trading them.
- "Propose again" asks the assistant for a fresh proposal (about 30 seconds).

**Open Japanese banks (at committee).** This is the showpiece.
- *Research* ran in the background: a plan, three parallel researchers, a red team and a verifier.
  - 45 claims: 27 supported, 18 partly supported, 0 unsupported.
  - 154 of 156 figures traced to evidence.
  - 167 evidence items: Nabd's own event studies and filings plus 17 searches restricted to official sites (BoJ, FSA,
    JPX, SEC).
- Point at one red-team finding: after 18 oil shocks the basket lagged SPY by 2.5% over 20 days (t −2.7). That is
  the argument against, computed, not asserted.
- Point at the memory catch: the red team noticed that the Equinor cap approved earlier (0.1%) differs from the
  weight now held. Nabd remembers decisions across ideas.
- *Portfolio fit*: budget use goes from 77% to 83%; the idea adds about 21 bp of tracking error.
- *Stress*: historical replays, factor shocks and a 2,000-path simulation.
- *Committee pack*: evidence, risk sign-off, and an exit plan with stop, target, review date and the triggers the
  research itself proposed.

**Open Quality energy producers (monitored).** After approval, the position is watched: health score, the exit
triggers, and an alert on the Ideas tab when one trips.

### 6:30 Ask Nabd: answers with figures the LLM cannot invent (2 min)

Press `/` or the Ask button in the dock. Tested questions:

1. "How would a Hormuz closure hit the whole portfolio?" Expect a bar chart and "6 of 6 figures traced".
2. "Brent against XLE and SPY over one year." Expect a line chart, then follow up with "and over three years?"
   to show it keeps the thread.

Point at the steps streaming (which tools it called) and the figure-check badge. *For the Head of AI:* Codex only
chooses tools and writes the words. Every number comes from a tool, charts are drawn from the tool's own data, and
any figure that cannot be traced to evidence in the same paragraph is flagged.

### 8:30 Forecasting: UAE GDP before FCSC publishes it (2½ min)

- The headline: the Q3 2026 non-oil nowcast (about −1.4%) against the last official figure (Q2 2026, −1.1%,
  published 9 October).
- **The shock test.** From April to July every model called a Q2 contraction while the last-release benchmark said
  +6.1%. FCSC published −1.1% in October.
- **Scored honestly.** A pseudo real-time backtest on first releases at three points in each quarter. The champion
  (bridge regression) has an error about a third below the benchmark for non-oil GDP and 45% below for real GDP.
- Run the Hormuz and Brent scenario to show the nowcast's sensitivity.
- *Caveat to say out loud:* about 16 quarters of target data, so the bands are wide. FCSC blocks automated access, so
  the release record is a sourced CSV an analyst maintains.

### 11:00 Fraud network: follow the money, not the rules (2½ min)

- The headline sentence: rules raise **350** separate alerts and catch **0** of 26 rings whole. Following the money
  finds the same laundering as **32** cases, and **91%** of the accounts it flags are laundering.
- The page opens on the strongest case as a **money flow**: money from outside on the left, the account where it
  enters, the accounts that pass it on, where it leaves. Arrow width is the amount.
- Press **Replay the money**: transfers light up in time order across banks, with the clock and the running total.
  Hover any account or arrow (or a row in the timeline) to see the same money highlighted everywhere.
- Open the mule ring (the largest case, about 60 accounts across six banks) to show scale, then switch methods
  (Rules → Money trail → Combined). *Whole network* shows where a case sits among every account.
- Turn on *Show labels* in the whole-network view to prove it against the truth.
- *Caveat:* the payments are synthetic (AMLSim-style, six banks, 14 days). The method is the point; calibration needs
  CBUAE payment data on premise.

### 13:30 Close: what each of you should take away (1½ min)

| Audience | What Nabd showed | What it needs next |
|---|---|---|
| Investment team | An idea becomes a committee pack with evidence, sizing, stress and exits in minutes, then stays monitored | Their real portfolio and limits; a licensed price feed |
| Head of AI | Agents that plan, use tools and verify; the LLM never produces a figure; every model run is recorded | Independent validation; Azure OpenAI UAE North or an on-premise model behind the same gateway |
| Head of Cyber | Local only, read-only sandboxed LLM with no shell or files, official-domain allowlist, validated inputs | Sign-in and roles, deployment inside CBUAE's network, a penetration test |
| CRO | Every decision and stage logged with who and when, exit triggers that alert, honest backtests against benchmarks | Model Management Standards validation, thresholds set by Risk |

## Questions you will get, and honest answers

- **"Does our data go to OpenAI?"** In this demo, prompts go to OpenAI through Codex, which is why it runs on open
  data only. In the client environment the same gateway points to Azure OpenAI UAE North or an on-premise model.
- **"Can the LLM make up a number?"** It can write one, but the figure check traces every figure in an answer to
  tool evidence in the same paragraph. Research verification removed 0 of 45 claims on the Japanese banks run.
- **"How good is the nowcast really?"** Better than the last-release benchmark by about a third on non-oil GDP, on
  9 scored quarters. That is too few to call it validated; it is enough to show the method works.
- **"Is the fraud precision real?"** It is measured against labelled synthetic data. On real payments, expect lower,
  and expect to tune the hold window and pass-through share with the AML team.
- **"Who approved this position?"** The audit log shows every stage, who acted and when. In the POC every user is
  "Investment team"; sign-in adds named roles.

## If something goes wrong

| Symptom | What to do |
|---|---|
| A page shows an error card | Press *Reload*. Nabd keeps running and no data is changed |
| The badge says *Reconnecting · polling* | The stream reconnects on its own and replays missed events; meanwhile pages poll |
| The badge says *Backend offline* | The API stopped: rerun `make dev` |
| Ask Nabd or research errors | Codex session or sign-in. Say so, show an existing research run, and carry on |
| Nothing loads | Check the API is running: <http://127.0.0.1:8000/api/system/health> |
