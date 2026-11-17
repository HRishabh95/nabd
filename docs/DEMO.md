# Nabd demo: 15 minutes

For the Investment team, the Economics department, AML and Fraud, the Head of AI, the Head of Cyber and the CRO.
One presenter drives, in dock order: Overview, Investment, Forecasting, Fraud network, Governance, then Ask Nabd.

The story for every page is the same: **CBUAE already does this work; Nabd shows what AI adds, and checks itself.**
Figures below are from the demo data on 17 Nov 2026. They move as data refreshes; say what the screen says.

## Before the room fills (10 minutes)

1. `make doctor`: every line green. If Codex is not signed in, run `codex login`.
2. Freeze the data so nothing moves mid-demo: set `NABD_REFRESH_ENABLED=false` in `nabd/.env`, then `make dev`.
3. Open <http://localhost:5173> in a browser window at least 1440 × 900 (text steps up a size at that width).
4. Warm up the slow parts so nothing waits in front of the room:
   - Ask Nabd one question (below).
   - Open Fraud network once: the AI note for C01 is written and cached.
   - Forecasting: press *Rerun nowcast* (12 seconds).
5. Investment: the benchmark is a notional commodity book (gold 30%, energy 22%, metals 23%, agriculture 6%, broad
   indices 10%, liquidity 9%); equities are data only. The pipeline is empty: add one or two commodity ideas the day
   before and run deep research on one (12 minutes) so a report and proposed split are ready.

**If Codex is unavailable**, everything except new ideas, research, fraud notes and Ask Nabd still works: screening
figures, portfolio fit, stress, the nowcast and fraud detection are Python models. Say so and carry on.

## The walkthrough

### 0:00 Overview (1 min)
Markets on the left (Gulf indices, global equities, rates, oil, gold, currencies); click one for its chart. News on
the right, filtered to what a reserve manager reads (oil, Gulf shipping, UAE economy, rates, central banks).
*Say:* "One screen of what moved and why, before we open anything."

### 1:00 Investment: from an idea to a decision (5 min)
1. Press **New idea** and type, for example, *"Oil prices fall as Hormuz reopens in 2027; hold less oil and protect
   the portfolio"* or *"Gold keeps rising as central banks buy and real yields fall; overweight gold for 6 months"*. Nabd writes the thesis (about 40 seconds) and proposes **what to look at**:
   names to buy or research, what to hold less of, and protection, each with a reason.
2. Point at the **check badges**: Nabd measures each suggestion against the data (how it moves with the idea, what it
   did on the idea's worst days). *"Data disagrees"* means the LLM's suggestion failed the test. "The AI proposes;
   the data decides."
3. Tick what to trade or press *Research*, then **Review and start research**: before anything runs, the screen
   shows the portfolio before and after, by asset class, and warns when the selection does not change exposure.
4. Open an idea that already has research: plan, investigation, red team, verification, and a **proposed split**
   of the portfolio within the risk budget, which *Use this split* adopts. Then portfolio fit, stress and the
   committee pack.

### 6:00 Forecasting: what AI adds to a GDP model (3 min)
1. **One model, two ways**: the same Kalman nowcast on hard data (shipping, trade, equities), and with an AI news
   signal added. The track-record chart shows what each said a month after every past quarter, against FCSC's first
   release, and the forecast to the end of 2027.
2. **Against the IMF**: real GDP 2026 −0.6% (with AI) against the IMF's −3.9%. The card shows the arithmetic: with
   Q1 and Q2 published, the IMF's figure needs Q3 and Q4 to average about −8.3%.
3. **Why it moved**: an exact split of the latest revision by input, with AI news tagged.
4. **What the AI read**: every headline behind the AI signal, with the label the LLM gave it. The signal is a
   diffusion index like a PMI balance (% stronger minus % weaker, shrunk in thin months); only headlines reporting
   actual UAE activity count (23% of those read). "This is the audit
   trail: nothing in the signal you cannot open and read."
*Say honestly:* AI news cut the error mainly in the Q2 2026 contraction; in calm quarters it adds nothing. With 13
published quarters, treat it as promising, not proven.

5. **Test the nowcast** (button at the top): switch inputs off and on and re-test in seconds; adding global market
   series makes it clearly worse, which shows why they are left out. *Score your own model*: download the template,
   fill CBUAE's past nowcasts, upload, and see them next to Kalman + AI and the average of the two.

### 9:00 Fraud network: one investigation, end to end (3 min)
1. The summary: 90,775 synthetic payments analysed, 266 suspicious, 32 networks, 91% precision against the labels.
2. **C01 opens on its own**: seven accounts at four banks passing AED 1.16 m around a loop in one afternoon. Numbers
   on the arrows are the order of transfers; click an account to trace the money onward and back.
3. **Money flow**: the same network left to right in time, one row per bank, with *Replay the money*.
4. **AI investigation**: why it was flagged, how the accounts connect, the telling transfers (click one to trace
   it) and what to examine next. Point at the last line: every transfer it cites is checked against the data, and
   it never saw the labels.
5. Open **C08** (fan-in) from its bubble to show a different pattern.
6. For "can we use real payment data?": press **What the AI saw** (the exact text, and what is never sent) and
   **Real payment data: how it stays safe**.

### What a sceptical economist will ask, and where to click
- *"Does the news really help?"* the track-record chart and *Test the nowcast → Switch inputs*: switch the AI news
  off and re-test; the error rises at quarter end and a month after for non-oil GDP.
- *"Why Kalman?"* the **Why Kalman?** button: mixed frequencies, missing data, built-in uncertainty, exact revision
  breakdown, standard at central banks.
- *"Why so far from the IMF's 7.7% for 2027?"* the IMF card: under the IMF's own reopening assumption the model gives
  about 9%; the gap is the assumption, not the model.
- *"How is a headline scored?"* **What the AI read → How the AI scores**, and the one-line reason under each headline.

### Governance (1 min, before Ask Nabd)
*Models*: one card per model saying what it does, the data, how it was tested, what the test found and what it
cannot show (for example the risk model: 3 exceptions in 250 days, Basel green, with filtered historical simulation),
and its **Validation pack** (purpose, data, method, results,
limits, run history, sign-off; print to PDF). Say: "Ready for your validators; not yet validated."
*AI evaluation*: research claims verified, fraud-note transfers matched, Ask Nabd figures traced, and human review
from the 👍 / 👎 under every AI output. **Label 10 headlines** measures the AI's news labels against your analysts.

### 12:00 Ask Nabd (1½ min)
Open the full page (**Ask Nabd → Open full page**): conversations on the left, the chat in the middle, and *About
you* on the right: pick a role (Investment, Economics, AML, Risk, Executive) and save preferences; answers say when a
saved preference shaped them.
Press `/` and ask, for example: *"What is Nabd's nowcast for UAE real GDP in 2026, and how does it compare with the
IMF?"* The answer cites its sources and shows *5 of 5 figures traced*: every number came from a tool.

### 13:30 Close (1½ min)

| Audience | What Nabd showed | What it needs next |
|---|---|---|
| Investment team | An idea becomes researched, sized and stress-tested in minutes, with the data checking the AI | Their real portfolio and limits; a licensed price feed |
| Economics | AI news measured inside a standard Kalman nowcast, with a track record and the IMF alongside | CBUAE's own indicators (credit, PMI, payments) in the same model; more history |
| AML and Fraud | A ring found by following the money, explained in plain words, every cited transfer checked | Real payment data under the bank's controls; tuning with investigators |
| Head of AI | The LLM proposes and writes; Python models measure; figures are traced and checked | Independent validation; Azure OpenAI UAE North or an on-premise model behind the same gateway |
| Head of Cyber | Local only; read-only LLM sandbox; official-domain allowlist; validated inputs | Sign-in and roles, deployment inside CBUAE's network, a penetration test |
| CRO | Every stage logged with who and when; honest backtests against benchmarks | Model Management Standards validation; thresholds set by Risk |

## Questions you will get, and honest answers

- **"Does our data go to OpenAI?"** In this demo, prompts go to OpenAI through Codex, which is why it runs on open
  and synthetic data only. In the client environment the same gateway points to Azure OpenAI UAE North or an
  on-premise model.
- **"Can the LLM make up a number?"** It can write one, but Ask Nabd traces every figure to tool evidence, research
  verifies its claims, and the fraud note keeps only transfers that exist in the data.
- **"Is the nowcast better than ours?"** Not claimed. It shows what adding AI news to a standard model does, measured
  honestly: it helped in the one contraction and not in calm quarters.
- **"Did the AI know the future when it read old news?"** Headlines were labelled shuffled and undated, so it judged
  each one on its text. It could still recognise a famous event from the words; that is stated on the model card.
- **"Is the fraud precision real?"** It is measured against labelled synthetic data. On real payments expect lower,
  and expect to tune with the AML team.

## If something goes wrong

| Symptom | What to do |
|---|---|
| A page shows an error card | Press *Reload*. Nabd keeps running and no data is changed |
| The badge says *Reconnecting · polling* | The stream reconnects on its own; pages poll meanwhile |
| The badge says *Backend offline* | The API stopped: rerun `make dev` |
| An AI note or answer takes long | First time for that network or question: about 40 seconds; it is cached after |
| Ask Nabd or research errors | Codex session or sign-in. Say so, show an existing research run, and carry on |
| Nothing loads | Check the API: <http://127.0.0.1:8000/api/system/health> |
