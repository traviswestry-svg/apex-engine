# APEX 68.3 — Dynamic-State Outcome Calibration

## Objective
Link frozen decision-time dynamic-state policy context to the existing APEX evidence/outcome ledger so policy effectiveness can be measured prospectively by regime without mutating live decision policy automatically.

## Added
- `engine/dynamic_state_outcome_calibration.py`
  - freezes event phase, gamma-term divergence/fragility, residual-pressure opposition, flow independence bucket, alert state, and exact policy penalties;
  - persists immutable context in `dynamic_state_decision_context` beside the existing evidence ledger;
  - joins context to existing `grading_results` outcomes;
  - reports sample size, win rate, directional move, MFE, and MAE by regime;
  - enforces advisory-only governance and minimum-sample readiness.

## Enhanced
- `engine/evidence_pipeline.py`
  - decision snapshots now persist immutable dynamic-state calibration context on first write;
  - no second outcome database is introduced.
- `engine/dynamic_state_routes.py`
  - adds read-only `GET /api/dynamic-state/calibration`.
- `templates/apex_os.html`
  - Dynamic State panel now surfaces calibration status, graded-context count, minimum bucket sample, and readiness.

## Calibration dimensions
- Event phase
- Gamma-term divergence
- Near-term gamma fragility
- Opposing residual pressure
- Flow-independence bucket
- Alert state

## Governance
- Advisory only.
- No automatic threshold mutation.
- No automatic confidence mutation.
- No automatic consensus-weight mutation.
- Human approval remains required for policy changes.
- Decision-time context is immutable after first persistence.

## Validation
40 focused regression tests passed, covering APEX 68.3, 68.2, 68.1, prior dynamic state, decision reasoning, Trade Director decision quality, Phase 38, and institutional narrative.
