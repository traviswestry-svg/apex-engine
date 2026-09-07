# APEX 68.4 — Dynamic-State Calibration Integrity & Promotion Governance

## Objective
Add statistical integrity, independent-sample enforcement, challenger-vs-incumbent calibration comparison, and explicit recommendation promotion governance to APEX 68.3 without allowing automatic production mutation.

## Changes
- Added `engine/dynamic_state_calibration_governance.py`.
- Added 95% Wilson confidence intervals.
- Added two-proportion challenger-vs-incumbent comparison with configurable effect-size and p-value gates.
- Enforced both raw sample minimums and flow-independence-weighted effective sample minimums.
- Added immutable calibration candidate definitions with integrity hashes.
- Added lifecycle: `COLLECTING → ELIGIBLE_FOR_REVIEW → APPROVED` plus `REJECTED`.
- Human actor is required for review; statistical assessment can only advance a candidate to `ELIGIBLE_FOR_REVIEW`.
- `APPROVED` means approved calibration recommendation only; `production_effect` remains `NONE` and handoff is required to `engine.production_governance`.
- Extended 68.3 calibration summaries with Wilson intervals and 68.4 governance metadata.
- Added read-only governance status to `/api/dynamic-state/calibration` and `/api/dynamic-state/calibration-governance`.
- Dashboard calibration line now surfaces counts eligible for review and approved.

## Safety / Governance
- No automatic threshold mutation.
- No automatic confidence mutation.
- No automatic consensus-weight mutation.
- No automatic production activation.
- Terminal approval does not deploy policy; existing production governance remains authoritative.

## Validation
Focused regression suite: **45 passed**.

Covered:
- APEX 68.4 calibration governance
- APEX 68.3 outcome calibration
- APEX 68.2 dynamic-state alert governance
- APEX 68.1 dynamic gamma/event state
- prior dynamic-state behavior
- decision reasoning consolidation
- Trade Director decision quality
- Trade Director Phase 38
- institutional narrative
