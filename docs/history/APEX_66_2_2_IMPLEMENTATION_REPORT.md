# APEX 66.2.2 — Historical Level Lifecycle Semantics

## Objective
Correct historical HLCE/registry diagnostics so a completed session is compared against the complete persisted session lifecycle rather than the current `active=1` universe.

## Implemented
- Added read-only `session_levels()` access to the complete `daily_levels` lifecycle for a selected session, including retired rows.
- Added canonical-ID-first historical identity reconciliation between canonical active-level registry records and HLCE session records.
- Retained `(kind, price)` fallback matching only for legacy rows without canonical IDs.
- `/api/level-calibration/active-levels/diagnostics` now reports historical registration identity separately from current active state.
- Added `registry_registered_for_session`, `hlce_registered_for_session`, `hlce_currently_active`, `hlce_retired_after_session`, `historical_identity_matches`, `historical_sync`, and `sync_semantics`.
- Preserved `registry_active_count`, `hlce_active_count`, and `in_sync` for backward compatibility; `in_sync` now reflects session-registration identity rather than live active-state equality for the selected evidence session.
- Level-source coverage now distinguishes `registered_for_session`, `active_during_session`, `currently_active`, and `retired_after_session`.
- Historical `unavailable` now means `registered_for_session == 0`, not `currently_active == 0`.
- Legacy `active` and `stale` counters remain as current-active and retired aliases for compatibility.

## Guardrails
- Diagnostic/read-only changes only.
- No collector changes.
- No scanner changes.
- No canonical active-level publisher changes.
- No execution-boundary or broker changes.
- No historical backfill.
- No fabricated levels, interactions, outcomes, or statistics.
- No decision or execution influence.
- No database migration.

## Release identity
- APEX version: `66.2.2`
- Build name: `Historical Level Lifecycle Semantics`
- Database schema version: `5` (unchanged)

## API changes
Enhanced response from:
- `GET /api/level-calibration/active-levels/diagnostics`

New fields:
- `registry_registered_for_session`
- `hlce_registered_for_session`
- `hlce_currently_active`
- `hlce_retired_after_session`
- `historical_identity_matches`
- `historical_sync`
- `sync_semantics=SESSION_REGISTRATION_IDENTITY`

Enhanced family objects from:
- `GET /api/learning/evidence-readiness`

New lifecycle fields per family:
- `registered_for_session`
- `active_during_session`
- `currently_active`
- `retired_after_session`

Semantic correction:
- `unavailable=true` only when no level in the family was registered for the effective session.

## Files added
- `tests/test_apex_66_2_2_historical_level_lifecycle.py`
- `APEX_66_2_2_IMPLEMENTATION_REPORT.md`
- `APEX_66_2_2_DEPLOYMENT_ROLLBACK.md`

## Files modified
- `engine/historical_level_calibration.py`
- `engine/historical_level_calibration_routes.py`
- `engine/evidence_accumulation_observatory.py`
- `engine/version.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_48_2_version.py`

## Files deprecated
None.

## Files removed
None.

## Database migration notes
No migration. Existing `daily_levels.canonical_level_id`, `active`, `valid_from`, and `valid_to` fields are read only. Production learning history is untouched.

## Validation
Broader APEX integrity/HLCE/execution regression set:
- 80 passed
- 0 failed
- 1 skipped

Skip reason:
- Flask-dependent route registration test could not import Flask in the isolated development runtime.

Focused 66.2.x lifecycle/session tests:
- 11 passed
- 0 failed

Python compilation:
- `engine/`: passed
- `app.py`: passed
- `scanner_worker.py`: passed
- `wsgi.py`: passed

## Validation limitations
- HTTP route execution was not exercised locally because Flask is unavailable in the isolated build runtime.
- Production `/data/apex_calibration.db` is not available in the build environment; production identity reconciliation must be verified after deployment.
- No broker I/O or order mutation path was invoked.

## Expected production validation
For `2026-08-07`, the historical diagnostic should no longer classify all 61 Friday registry levels as `registry_only` merely because their HLCE active flags were retired after the session. Expected fields should resemble:

```json
{
  "registry_registered_for_session": 61,
  "hlce_registered_for_session": 61,
  "hlce_currently_active": 0,
  "hlce_retired_after_session": 61,
  "historical_sync": true,
  "sync_semantics": "SESSION_REGISTRATION_IDENTITY"
}
```

Exact match counts remain evidence-dependent and are not fabricated by this release.
