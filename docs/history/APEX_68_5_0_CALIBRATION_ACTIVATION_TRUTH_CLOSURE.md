# APEX 68.5.0 — Calibration Activation & Truth Closure

## Purpose
Close the verified gap between statistically governed calibration recommendations and controlled production influence without enabling autonomous promotion or changing execution authority.

## Changes
- Ratchets canonical release identity and Capability Registry to 68.5.0.
- Adds `engine.calibration_activation` as the single manual activation boundary for approved dynamic-state calibration candidates.
- Enforces candidate-integrity revalidation, hard per-adjustment bounds, aggregate caps, immutable activation provenance, and explicit rollback.
- Keeps event suppression, WATCH_ONLY state, direction generation, risk and execution authority outside calibration control.
- Applies active calibration only as bounded additive adjustments to existing dynamic-state threshold/conviction/consensus penalties.
- Moves the three root `app.py` store families (tracking, signal spine, review/replay) to canonical SQLite connection policy without changing DB paths or schemas.
- Extends the post-persistence architecture inventory to include root `app.py`.
- Adds calibration activation/readout API routes and an end-to-end decision-outcome-calibration-review-activation-rollback regression test.

## Activation lifecycle
`COLLECTING → ELIGIBLE_FOR_REVIEW → APPROVED → ACTIVE → ROLLED_BACK`

Activation remains explicitly human-triggered. There is no automatic promotion or automatic production activation.

## Safety invariants
- No new direction generation.
- No mutation of event suppression or WATCH_ONLY decisions.
- No execution authority.
- No broker submission changes.
- No risk-rule changes.
- No DB path/schema migration for the root app stores.
- HLCE automatic evidence blend is unchanged.
