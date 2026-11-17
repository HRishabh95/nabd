# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML, CSS and vanilla JavaScript, served locally (`python3 -m http.server`). Charts drawn in SVG by hand or with the bundled charts.js. No framework.

## Users

Senior people at the Central Bank of the UAE (CBUAE) seeing a pitch and then a proof of concept: the investment team, the Head of AI, the Head of Cyber and the Chief Risk Officer. Later, daily users in economic research, financial stability, payment systems and the governor's office. They are expert economists and risk professionals, sceptical of AI hype, and read the screen on office monitors and a meeting-room display.

## Product Purpose

Nabd ("pulse") is a sovereign economic-intelligence platform that runs inside CBUAE. It measures the UAE non-oil economy daily from payment flows (UAEFTS, Aani, WPS, cards), maps the firm-to-firm payment network, and runs models on that network. Success in the pitch: the room sees something it could not get from ChatGPT or Claude and asks for a paid on-premise proof of concept.

## Positioning

General assistants can talk about the economy; Nabd computes on CBUAE's own data. Every number comes from a model run on that data, with a run ID, data vintage and audit trail. The language model only translates questions into model parameters and explains results; it never writes a figure.

## Operating Context

A pitch meeting first, then daily use. Data is classified: firm and account level data stays on premise; only aggregates may reach a hosted model in Azure UAE North. Information barriers apply between departments (for example, Investment sees sector signals only, no firm names).

## Capabilities and Constraints

Lead capabilities (the main screens):
- Scenario runs: a scenario in plain words becomes explicit, editable model parameters; Nabd runs 1,000 simulations on the firm network and shows the outcome distribution, with run ID, compute time and data vintage.
- What moved the nowcast: the daily non-oil nowcast with its uncertainty, and the contribution of each data release to this week's revision.
- Time machine and track record: what Nabd showed on any past date (real-time vintages), and its lead against the official GDP release delay.

Secondary: the firm network map, the cross-bank fraud view, governance (where each model runs, audit log, guardrails).

The prototype has a role switcher (Governor's Office, Investment, Financial Stability, Payment Systems); changing role visibly applies the information barrier.

Terminology: nowcast, real-time vintage, run, scenario, liquidity cover, systemic firm, mule ring.

## Brand Commitments

Name: Nabd, Arabic نبض. Must work in English and Arabic later (right-to-left). CBUAE's own published forecast must not be framed as the loser; Nabd's lead is measured against the official GDP release delay.

## Evidence on Hand

None real. All data in the prototype is synthetic and must be labelled as illustrative. Do not invent customers, benchmarks, accuracy claims presented as real, or CBUAE statements. The forecast figures 5.1% and 1.3% came from the user's research and must be verified before a real meeting.

## Product Principles

1. Show the engine, not just the answer: parameters, runs and provenance are visible.
2. Numbers come from models, words from the language model; every figure traces to a run.
3. Uncertainty is shown, never hidden: ranges, fans and distributions instead of single points.
4. Governance is a feature: roles, barriers and audit are visible in the interface.
5. Professional, not AI-generated: earned familiarity, precision and restraint.
