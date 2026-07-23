# APEX Trade Director Phase 35 — Multi-Horizon Trade Function Router

## Build purpose
Phase 35 rebuilds Phase 34's global environment-quality sizing gate into a style-relative opportunity and allocation workflow. APEX continues to use one shared institutional evidence layer, but now ranks the market's fit for multiple trade functions instead of declaring the entire environment good or bad.

## Trade functions
- Quick Scalp — under 5 minutes
- 15-Minute Scalp — 5 to 15 minutes
- 30-Minute Scalp — 15 to 30 minutes
- Intraday Trade — 30 minutes through the cash close
- Swing Trade — multi-day
- LEAP — long-duration thesis

## Implementation
### Shared evidence router
`engine/trade_director_trade_function_router.py`
- Consumes dealer/gamma, auction, flow, volatility, trend, liquidity, higher-timeframe, catalyst, fundamental, and thesis evidence.
- Produces a ranked style-fit table with score, grade, holding window, entry style, reasons, and blockers.
- Supports automatic best-fit routing or explicit human selection.
- Fails closed when evidence coverage is insufficient.
- Labels all scores as heuristic priors pending Phase 31/32 calibration; they are not represented as validated probabilities.

### Style-aware session allocation
`engine/trade_director_session_allocation.py`
- Preserves the five-trade daily cap and 1 → 3 → 4 → 3 → 3 progression.
- Replaces the universal high-quality-environment gate with selected-function fit.
- Reserves the four-contract tier for an A+ fit in the selected function.
- Allows A/A-/B-class style fits to use the governed baseline up to three contracts.
- Reduces missing/weak style fit to one discovery contract.
- Preserves daily-risk reductions and consecutive-loss lockout.
- Adds trade-function, style-fit grade, and style-fit score to confirmed-trade records with backward-compatible schema migration.

### Assistant dashboard
- Market directive/game-plan card remains first on `/assistant`.
- Trade Function Router & Session Allocation renders second.
- Provides Auto Best Fit plus manual selection for all six functions.
- Displays ranked style fit, hold window, planned allocation, recommended allocation, risk remaining, and limitations.
- Manual confirmation records the selected trade function and fit with the trade.
- No broker placement, modification, cancellation, or authorization was enabled.

## API
- `GET|POST /api/trade-function-router`
- Enhanced `GET /api/session-allocation`
- Existing `POST /api/session-allocation/reset`
- Existing `POST /api/position` now records function and style-fit metadata.

## Files changed
- `engine/trade_director_trade_function_router.py` (new)
- `engine/trade_director_session_allocation.py`
- `app.py`
- `templates/assistant.html`
- `tests/test_trade_director_phase35.py` (new)
- `APEX_TRADE_DIRECTOR_PHASE_35_BUILD.md`

## Validation
- Python compilation: PASS
- Assistant dashboard JavaScript syntax: PASS
- Phase 35 focused tests: 6 passed, 0 failed
- Phase 34 + 35 compatibility tests: 11 passed, 0 failed
- Trade Director Phase 13–35 regression suite: 99 passed, 0 failed
- Broader dependency-free regression execution: 1,024 passed
- Three additional dependency-free-selected tests remained blocked by missing Flask imports.
- Full repository collection remains blocked across 42 Flask-dependent modules because Flask is unavailable in this build container.
- Confirmation gate: preserved
- Autonomous live trading: disabled
- Broker execution behavior: unchanged

## Deployment notes
Deploy the complete repository or overlay the changed-files archive onto the current Phase 34 deployment. Render must install the repository's normal Flask dependencies. After deployment, verify `/assistant`, `/api/trade-function-router`, and `/api/session-allocation` during both market-closed and live-session states.
