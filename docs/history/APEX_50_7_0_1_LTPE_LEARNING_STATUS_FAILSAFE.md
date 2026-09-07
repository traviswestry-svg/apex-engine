# APEX 50.7.0.1 — LTPE Learning Status Fail-Safe Repair

## Objective
Prevent `/api/level-calibration/transitions/learning-status` and the manual learning-cycle route from leaking Flask's generic HTML 500 response when the persistent Render calibration database has an older/partial schema, a transient SQLite error, or a status-query failure.

## Changes
- Made LTPE `learning_status()` schema-aware using SQLite `PRAGMA table_info` inspection.
- Added defensive scalar reads with stage-specific diagnostics.
- Made persistent-store initialization failures non-fatal to status reporting.
- Added explicit `HEALTHY` / `DEGRADED` operational status and `failure_stage`.
- Added table-presence diagnostics without fabricating learning counts or probabilities.
- Added route-level exception containment for both learning-status and manual learning-cycle endpoints; failures now return structured JSON rather than Flask HTML 500 pages.
- Preserved `EVIDENCE_ONLY_NO_FABRICATION` probability policy.

## Expected GET
`https://apex-engine-dashboard.onrender.com/api/level-calibration/transitions/learning-status`

Healthy example:
```json
{"ok":true,"status":"HEALTHY","state":"COLLECTING","observations":0,"diagnostics":[]}
```

Degraded example:
```json
{"ok":false,"status":"DEGRADED","failure_stage":"STORE_INITIALIZATION","diagnostics":[...]}
```

## Validation
- Legacy/partial SQLite schema fails safe: PASS.
- Fresh/current schema remains healthy: PASS.
- APEX 50.6/50.7/65.6/Monday-readiness regression subset: 71/71 PASS.
- Python compilation: PASS.
