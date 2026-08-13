# APEX 66.0 — Canonical Active Level Registry

## Objective
Prevent HLCE from calibrating against stale, duplicated, wrong-session, or taxonomically fragmented institutional levels while preserving APEX 65.7.5 scanner ownership and APEX 65.9 interaction detection.

## Findings repaired
- Daily Key Levels exposed 47 kinds while HLCE had a smaller/fragmented taxonomy.
- OR5 and OR15 were collapsed to generic OR high/low.
- Durable canonical context `latest()` was not constrained to the active target session.
- HLCE daily level registration accumulated changed intraday prices indefinitely.
- Collector `_sync_tracks()` added new rows but never retired superseded rows.
- Scanner consumed the durable context as a snapshot, not an explicit active-level registry.

## Implementation
### `engine/canonical_session_context.py`
- Added `canonical_active_levels` registry table in the existing canonical-context DB.
- Added canonical taxonomy normalization.
- Latest canonical publication is authoritative for active rows; prior revisions remain historical with `valid_to` and `active=0`.
- Added exact-session `latest(..., target_session_date=...)` lookup.
- Added `active_levels(...)` with lazy migration from an already-persisted exact-session context after deployment.

### `scanner_worker.py`
- Scanner resolves the current New York session date.
- Reads only exact-session active registry rows.
- Falls back to exact-session durable context only when registry rows are unavailable.
- Exposes active registry source/count in the HLCE snapshot.

### `engine/historical_level_calibration.py`
- Expanded/normalized the canonical level vocabulary so all 47 Daily Key Level kinds map cleanly.
- Preserved OR5/OR15 identity instead of collapsing them.
- Added migration-safe lifecycle columns to `daily_levels`: `canonical_level_id`, `active`, `revision`, `valid_from`, `valid_to`.
- Current snapshot becomes authoritative for the active HLCE universe.
- Superseded prices are retired, not deleted, preserving historical evidence.
- Collector removes retired tracks while preserving state for still-active rows.
- Existing idempotent registration remains backward compatible (`skipped` retained).

### `engine/historical_level_calibration_routes.py`
Added read-only diagnostic endpoint:
`GET /api/level-calibration/active-levels/diagnostics`

It compares canonical active registry rows with HLCE active rows for the exact session and reports `in_sync`, `registry_only`, and `hlce_only`.

## Safety / authority
- No change to scanner single-owner architecture.
- No change to interaction thresholds or 65.9 crossing detection.
- No change to grading, probabilities, risk, canonical decisions, or execution.
- No synthetic/backfilled interactions or outcomes.

## Validation
- Daily Key Level taxonomy: 47 source kinds / 47 normalized unique / 0 unmapped.
- Targeted regression suite: 35 passed.
- Python compilation passed for all changed modules.
