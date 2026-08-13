# APEX Trade Director Phase 36 Build

## Phase
**Phase 36 — Precision Entry & Momentum Lifecycle**

## Purpose
Phase 36 aligns APEX with the user's fast SPX options execution style. Entry quality is evaluated separately from broad institutional confidence. After the trader manually confirms the actual option fill, APEX measures premium movement from that fill and provides advisory lifecycle instructions.

## Governing Rules
- Entry quality is the primary Momentum Burst gate.
- Default profit-expansion objective: **+$2.00 premium** from the confirmed option fill.
- Governed adverse exit range: **-$2.00 to -$3.00 premium** from the confirmed fill; default **-$2.50**.
- Time in trade is secondary to premium behavior, market structure, and momentum.
- All outputs are advisory. APEX does not place, modify, or close broker orders.
- The existing confirmation gate remains active.

## Backend Implementation
- Added `engine/trade_director_momentum_lifecycle.py`.
- Added independent entry-quality scoring with explicit data coverage and fail-closed behavior.
- Added Momentum Burst premium lifecycle states:
  - `AWAITING_ENTRY_PREMIUM`
  - `AWAITING_LIVE_PREMIUM`
  - `ENTRY_TEST`
  - `MOMENTUM_EXPANDING`
  - `DEFENDING_ENTRY`
  - `PROFIT_NOT_YET_CONFIRMED`
  - `EXPANSION_OBJECTIVE_REACHED`
  - `ENTRY_THESIS_FAILED`
- Added advisory recommendations including `HOLD`, `PROTECT`, `TAKE_PROFIT`, and `EXIT_NOW`.
- Updated the Phase 35 router with a seventh function: `MOMENTUM_BURST`.
- Confirmed position records now retain the selected trade function, entry-quality snapshot, +$2 target, and governed adverse threshold.

## API Integration
- `GET|POST /api/position/momentum-lifecycle`
- `POST /api/entry-quality`
- `/api/position/action` now returns the refreshed Phase 36 lifecycle after a manual premium update.

## Dashboard Integration
The `/assistant` active-trade surface now includes a **Precision Entry & Momentum Lifecycle** panel showing:
- Entry-quality grade
- Actual entry premium
- Current premium
- Premium change
- Profit-trigger premium
- Adverse-trigger premium
- Current lifecycle state
- Advisory action and reason

The manual premium synchronization remains the source of truth unless a broker/data integration supplies the current contract premium in a later governed phase.

## Database / Schema
No new database table was required. Phase 36 state is attached to the existing manually confirmed active-position record. Phase 31/32 remain responsible for immutable evidence and subsequent outcome analysis.

## Tests
- Phase 36 focused tests: **8 passed, 0 failed**
- Phase 34–36 compatibility slice: **19 passed, 0 failed**
- Trade Director Phase 13–36 regression suite: **107 passed, 0 failed**

## Validation
- Python compilation: **PASSED**
- Repository Python compile-all: **PASSED**
- Assistant inline JavaScript syntax (`node --check`): **PASSED**
- Static route and dashboard integration: **PASSED**
- Confirmation gate: **PRESERVED**
- Autonomous broker execution: **DISABLED / UNCHANGED**

## Full-suite limitation
The complete repository suite could not collect in this build container because the Flask package is absent. Pytest reported **42 collection errors**, all rooted in `ModuleNotFoundError: No module named 'flask'`. These checks are documented as blocked and are not reported as passing. The repository declares Flask in `requirements.txt` for the normal Render deployment environment.

## Upgrade Notes
1. Deploy the complete Phase 36 repository or copy the changed-files archive into the existing repository while preserving paths.
2. Allow Render to install `requirements.txt` and redeploy.
3. Confirm a trade through the existing **I'M IN** workflow using the actual option fill premium.
4. Update live premium from the active-trade panel. APEX will calculate change from the confirmed fill and display the lifecycle recommendation.
5. `TAKE_PROFIT` and `EXIT_NOW` are instructions to the trader; they do not transmit broker orders.
