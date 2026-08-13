# APEX 18.0.6 — Trade Refusal Replay Engine

Runtime version: `11.0.4_TRADE_REFUSAL_REPLAY`

## Objective

Turn every governed premium refusal into a measurable counterfactual after the
cash session, without placing or modifying orders and without fabricating
missing strikes, quotes, bars, or market intent.

## Delivered

- Deterministic replay of refused 0DTE bull-put, bear-call, and iron-condor candidates.
- Forward-bar windowing from the original refusal timestamp through the 4:00 PM ET cash close.
- Path-aware short-strike breach detection.
- Modeled expiration P&L using the exact captured candidate strikes and entry credit.
- Outcome taxonomy: `AVOIDED_STOP`, `AVOIDED_LOSS`, `MISSED_WIN`, `NEUTRAL`, `NOT_EXECUTABLE`, and `NO_DATA`.
- Idempotent grading: a refusal can be graded only once.
- Two-day retry window before a missing-bar replay is finalized as `NO_DATA`.
- Replay scorecard with refusal precision, capital-protecting refusals, missed winners, pending count, outcome distribution, and aggregate modeled counterfactual P&L.
- SQLite schema evolution using additive, non-destructive columns.
- Read-only replay endpoint and explicit POST run endpoint.

## API

- `GET /api/premium_discipline/replay`
- `POST /api/premium_discipline/replay/run`
- `GET /api/premium_discipline/scorecard` now includes the replay scorecard.

## Governance

The replay engine is analytical only. It does not alter the original decision,
submit broker orders, retroactively approve a trade, or use future information
when making the original eligibility decision.
