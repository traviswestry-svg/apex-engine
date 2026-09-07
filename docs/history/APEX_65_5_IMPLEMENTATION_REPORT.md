# APEX 65.5 — Safe Physical Cleanup & Legacy Route Isolation

## Scope
Production stabilization and backend consolidation only. No signal, scoring, risk, broker, order, or execution behavior was intentionally changed.

## Changes
- Removed three modules proven to have no runtime/test/config/dynamic-loader references:
  - `engine/conviction_calibrator.py`
  - `engine/decision_contract.py`
  - `engine/evidence_matrix.py`
- Removed duplicate runtime test `engine/director/test_active_trade_director.py`; canonical copy remains at `tests/test_active_trade_director.py`.
- Added `engine/institutional_route_registry.py` as the canonical registration boundary for the legacy institutional roadmap route families.
- `app.py` no longer directly imports the 300-route institutional roadmap registrar; registration is delegated through the new boundary with paths/handlers preserved.
- Added a regression guard preventing `test_*.py` modules from being placed under `engine/`.
- Advanced dependency/consolidation schemas and composition build identity to 65.5.

## Post-build static inventory
- Engine modules: 309
- ACTIVE: 285
- COMPATIBILITY: 7
- DORMANT: 4
- ORPHANED: 13
- Cleanup candidates: 24
- Monday-critical engines: 12
- Monday-critical missing: 0
- Monday-critical non-active: 0
- Manual removal review: 0
- Automatic deletions: 0

## Validation
- APEX 65.x regression set: 31/31 PASS
- Repository Python compile: PASS
- All dashboard JavaScript syntax checks: PASS
- Additional legacy Flask-dependent test collection could not run in this build environment because Flask is not installed in the local harness; this is an environment/dependency issue, not a 65.5 test failure.

## Required deletion on deployment
Because a changed-files ZIP cannot remove files from an existing repository by overwrite, delete the four paths listed in `APEX_65_5_DELETE_FILES.txt` when applying this build.
