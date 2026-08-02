# APEX 50.7.0 — Level Transition Learning Activation

## Objective
Activate the evidence collection loop behind the Level Transition Probability Engine so live HLCE interactions automatically mature into level-to-level transition observations and statistics.

## Changes
- Added `50.7.0_LEVEL_TRANSITION_LEARNING_ACTIVATION` operational identity.
- Added `run_learning_cycle()` as the canonical idempotent LTPE learning hook.
- Each HLCE tick now grades interactions, records newly eligible transitions, and rebuilds transition statistics only when new observations are written.
- Added a non-blocking startup recovery sweep so interactions that matured during a Render restart/deploy are graded and processed immediately.
- Added `GET /api/level-calibration/transitions/learning-status` with explicit states: `COLLECTING`, `WAITING_FOR_MATURITY`, `READY_TO_GRADE`, and `READY_TO_RECORD`.
- Added `POST /api/level-calibration/transitions/learn` for a network-free/manual evidence catch-up cycle.
- Historical Calibration dashboard now shows live observation/pending/maturity counts.

## Evidence policy
No probability is emitted without historical observations. Existing `MIN_STAT_SAMPLE` gating and `EVIDENCE_ONLY_NO_FABRICATION` semantics remain unchanged.

## Safety
This build performs no broker calls and no provider/network calls from LTPE learning. It reads/writes only the existing HLCE SQLite evidence store.
