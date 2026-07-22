# APEX Trade Director Phase 11 — Institutional Portfolio & Session Intelligence

## Delivered

- Session Commander with realized, unrealized, and net session P/L
- Daily risk-budget accounting and remaining-risk display
- Adaptive session modes: OBSERVATION, ATTACK, DEFENSE, RECOVERY, LOCK_PROFIT, STOP_TRADING
- Dynamic contract-sizing guidance based on confidence, Trade Health, premium risk, remaining capacity, and session mode
- Institutional session scorecard
- Capital-efficiency measurement
- Strategy performance summaries from Phase 6 user-confirmed outcomes
- Mission Control panel on the Active Trade Director dashboard
- New session-intelligence API endpoint

## New endpoint

- `GET /api/position/session-intelligence`

## New module

- `engine/trade_director_session_intelligence.py`

## Optional environment settings

- `APEX_MAX_DAILY_RISK=2000`
- `APEX_MAX_DAILY_LOSS=1000`
- `APEX_MAX_DAILY_TRADES=3`
- `APEX_MAX_CONTRACTS=3`
- `APEX_SESSION_CUTOFF=11:30`

## Safety architecture

Phase 11 is analytical and advisory. It does not perform provider requests, start workers, initialize persistence on import, or place broker orders. Phase 9 remains authoritative for trade-level risk checks, and Phase 10 remains authoritative for execution confirmation and broker reconciliation.

## Validation

- Python compilation passed for `app.py` and the Phase 11 module
- Dashboard JavaScript syntax passed
- Phase 11 session-mode, risk-budget, sizing, and strategy-scorecard smoke tests passed
- Active Trade Director regression suite: 30 passed
- ZIP integrity checks passed
