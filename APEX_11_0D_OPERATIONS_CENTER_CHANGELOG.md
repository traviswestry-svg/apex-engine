# APEX 11.0D — Operations Center

## Added
- Read-only Operations Center at `/apex_os/operations`.
- System Health, API Explorer, Recommendation Ledger, Calibration Readiness,
  Diagnostics, and Release & Architecture tabs.
- Dynamic inventory of every registered Flask route.
- OpenAPI-style route manifest and endpoint statistics.
- Consolidated operational checks with explicit PASS/WARN/FAIL/DISABLED/BLOCKED states.
- Individual checks for application, database, data freshness, providers,
  recommendation ledger, outcome grader, chain quality, execution, clock,
  version consistency, calibration, similarity, learning safety, end-to-end
  decision path, alerts, and scheduler visibility.
- Operations navigation link on the Institutional OS dashboard.

## Safety
- All new system checks and endpoint inventory routes are GET-only.
- History-dependent systems remain BLOCKED rather than presenting fabricated
  calibration or similarity readiness.
- Operations registration is isolated and non-fatal to the trading application.

## Validation
- Python compilation passed for `app.py` and `engine/operations_routes.py`.
- 4 focused route tests passed.
