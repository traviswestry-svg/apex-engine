# APEX Trade Director Phase 34 — Session Allocation & Risk Manager

## Scope
Phase 34 adds a governed, advisory-only daily allocation plan and restores the Active Trade Director market-status/game-plan card to the top of `/assistant`.

## Trading policy implemented
- Maximum confirmed trades per session: 5
- Baseline contract progression: 1 → 3 → 4 → 3 → 3 adaptive cap
- Four-contract allocation requires a HIGH_QUALITY environment
- Unknown/poor environments reduce allocation to discovery size
- Two consecutive losses produce a fail-closed allocation lockout
- Remaining risk budget can only reduce, never increase, planned size
- All allocation remains manually confirmed; no broker action is enabled

## Files
- `engine/trade_director_session_allocation.py`
- `app.py`
- `templates/assistant.html`
- `tests/test_trade_director_phase34.py`
- `APEX_TRADE_DIRECTOR_PHASE_34_BUILD.md`

## API
- `GET /api/session-allocation`
- `POST /api/session-allocation/reset`
- Confirmed manual positions are recorded through the existing `POST /api/position` path.

## UI
The market-open/closed directive card (`#app`) now renders first beneath navigation. The allocation panel follows it, before manual confirmation and supporting intelligence.

## Validation
- Python compilation: PASS
- Trade Director Phase 13–34 regression suite: 93 passed, 0 failed
- Phase 34 focused tests: 5 passed, 0 failed
- Confirmation gate: preserved
- Broker execution: disabled/unchanged
- ZIP integrity: verified after packaging
