# APEX 69.10.32 — Canonical Excursion Semantics & Session-Phase Attribution Closure

## Scope
Read-only observational closure over immutable Decision Outcome Attribution evidence.

## Canonical excursion semantics
The existing 68.6 grader stores direction-adjusted extrema over forward price samples only. Because the decision entry itself is not necessarily a `price_samples` row, an entirely adverse forward window can legitimately store a negative maximum and an entirely favorable window can store a positive minimum. 69.10.32 does not rewrite those rows. It exposes a deterministic entry-anchored projection:

- canonical MFE = max(0, stored direction-adjusted MFE)
- canonical MAE = min(0, stored direction-adjusted MAE)

The original values remain visible as `stored_mfe` / `stored_mae`, with `projection_only=true`.

## Session phases
All phase attribution uses `America/New_York` via `zoneinfo`:
- PREMARKET: before 09:30
- OPEN_DISCOVERY: 09:30–10:00
- MORNING_DEVELOPMENT: 10:00–11:00
- LATE_MORNING: 11:00–11:30
- MIDDAY: 11:30–13:00
- AFTERNOON: 13:00+

## Routes
- `/api/effectiveness/canonical-excursion-session-phase`
- `/api/effectiveness/canonical-excursions?limit=500`

## Governance
No trade-decision, threshold, learning-eligibility, calibration, broker, or execution-authority changes. Excursions remain post-outcome attribution only. Session phase is context only. Historical evidence is immutable.

## Validation
- Python compilation: PASS
- Focused 69.10.30–69.10.32 tests: 12 passed
- Full `tests/test_apex_69_10_*.py` closure suite: 200 passed
