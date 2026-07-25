# APEX Trade Director Phase 38 — Institutional Intent & Flow Persistence

## Objective
Stop interpreting large calls as automatically bullish or large puts as automatically bearish. Phase 38 uses the order date/time, expiration, strike proximity, current market regime, dealer gamma, open-interest change, subsequent flow, and market reaction to estimate likely institutional intent and whether the order still matters now.

## Added
- `engine/trade_director_institutional_intent.py`
- `tests/test_trade_director_phase38.py`
- APIs:
  - `GET /api/institutional-intent/status`
  - `POST /api/institutional-intent/evaluate`
  - `POST /api/institutional-intent/batch`
- `/assistant` Institutional Intent panel
- Coordinated-scan integration when `large_orders`, `options_blocks`, or `institutional_orders` are present
- Append-only SQLite evidence at `apex_institutional_intent.db`

## Core outputs
- Likely intent and probability distribution
- Trade age and days to expiration
- Expiration bucket and relevance to the selected trade function
- Persistence score
- Current influence
- Signed directional value
- Momentum Burst impact

## Important limitation
Intent is probabilistic. Public flow cannot prove beneficial ownership, opening/closing status when the provider does not supply it, or hidden multi-leg relationships. Phase 38 fails toward neutral/uncertain rather than fabricating certainty.

## Execution policy
Advisory only. No broker orders are placed, modified, or closed.
