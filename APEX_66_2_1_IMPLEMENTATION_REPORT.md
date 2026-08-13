# APEX 66.2.1 — Session-Aware Evidence Diagnostics

## Objective
Correct non-trading-day HLCE observability without changing evidence collection, grading, canonical active-level publication, decision logic, or execution governance.

## Implemented
- Added shared HLCE evidence-session resolution using existing canonical session intelligence plus persisted `daily_levels` history.
- Diagnostics now distinguish `requested_date` from `effective_session_date`.
- Automatic diagnostics resolve weekends/non-session dates to the most recent persisted trading session on or before the canonical source session.
- Explicit `?session_date=YYYY-MM-DD` overrides are honored exactly for historical inspection.
- `/api/learning/evidence-readiness` now accepts `symbol` and `session_date` query parameters.
- `/api/level-calibration/active-levels/diagnostics` uses the same authoritative session resolver.
- Invalid explicit session dates return HTTP 400 instead of silently falling back.

## Guardrails
- Read-only diagnostics only.
- No collector changes.
- No historical backfill.
- No level synthesis.
- No decision influence.
- No execution influence.
- No database migration.

## Release identity
- APEX version: `66.2.1`
- Build name: `Session-Aware Evidence Diagnostics`
- Release series: `APEX 66`
- Database schema version: unchanged (`5`)

## API changes
Enhanced, backward-compatible query support:
- `GET /api/learning/evidence-readiness?symbol=SPX&session_date=YYYY-MM-DD`
- `GET /api/level-calibration/active-levels/diagnostics?symbol=SPX&session_date=YYYY-MM-DD`

Both diagnostic responses preserve `session_date` as the effective session and add:
- `requested_date`
- `effective_session_date`
- `session_resolution`
- `market_session_today`

Automatic resolution uses the canonical HLCE source session and the most recent persisted `daily_levels` session on or before it. Explicit session overrides are never silently changed.

## Files added
- `tests/test_apex_66_2_1_session_aware_diagnostics.py`
- `APEX_66_2_1_IMPLEMENTATION_REPORT.md`
- `APEX_66_2_1_DEPLOYMENT_ROLLBACK.md`

## Files modified
- `engine/historical_level_calibration.py`
- `engine/historical_level_calibration_routes.py`
- `engine/evidence_accumulation_observatory.py`
- `engine/evidence_accumulation_routes.py`
- `engine/version.py`
- `config/apex_release_manifest.json`
- `config/apex_capability_registry.yaml`
- `tests/test_apex_48_2_version.py`

## Files deprecated
None.

## Files removed
None.

## Database migration notes
No migration. All new session resolution reads existing `daily_levels` data in read-only mode. Production learning history is untouched.

## Validation
Targeted APEX 65–66 integrity/HLCE suite:
- 58 passed
- 0 failed
- 1 skipped

Skip reason:
- Flask-dependent route registration test could not import Flask in the isolated development runtime.

Full-suite collection was attempted and was blocked by the same environment limitation: 63 test modules import Flask directly and could not be collected because Flask is unavailable in the isolated runtime. This is not an application failure; the Render production build installs Flask 3.0.3 from `requirements.txt`.

Python compilation passed for all modified Python files.

## Validation limitations
- HTTP route execution was not exercised locally because Flask is unavailable in the isolated build runtime.
- Live production `/data/apex_calibration.db` is not present in the build environment, so Friday 2026-08-07 family counts must be verified after deployment.
- No broker I/O or execution path was modified or invoked.

## Recommended production validation
After deployment on a non-trading day, call `/api/learning/evidence-readiness`. The expected shape is:

```json
{
  "level_source_coverage": {
    "requested_date": "2026-08-08",
    "effective_session_date": "2026-08-07",
    "session_resolution": "MOST_RECENT_REGISTERED_TRADING_SESSION",
    "market_session_today": false
  }
}
```

Then inspect the same endpoint with `?session_date=2026-08-07` and compare level-family counts against `/api/level-calibration/active-levels/diagnostics?session_date=2026-08-07`.
