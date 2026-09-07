# APEX Trade Director Phase 39 — Subminute Execution Engine

## Objective
Use 15-second and 30-second bars for precise execution of 1–3 minute SPX option-premium scalps without allowing noisy subminute data to invent market direction.

## Implemented
- Added `engine/trade_director_subminute_execution.py`.
- Added `POST /api/subminute-execution/evaluate`.
- Added higher-timeframe authority gates: valid 1-minute setup, confidence, data freshness, risk eligibility, and spread quality.
- Added separate 15-second and 30-second impulse, alignment, stall, rejection, and reversal measurements.
- Added entry states: `WAIT`, `ARM_ENTRY`, and `ENTRY_ELIGIBLE`.
- Added active-trade states for premium expansion, $1–$3 target capture, momentum fade, and the governed 180-second timebox.
- Preserved manual confirmation and advisory-only execution.

## Design rule
Subminute data may time an entry or exit. It may not create CALL/PUT direction. Direction must come from the validated higher-timeframe setup.

## Files changed
- `app.py`
- `engine/trade_director_subminute_execution.py`
- `tests/test_trade_director_phase39.py`
- `APEX_TRADE_DIRECTOR_PHASE_39_BUILD.md`
