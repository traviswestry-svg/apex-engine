# APEX 65.4 — Backend Runtime Consolidation

## Scope
65.4 begins structural backend consolidation without changing signal, scoring,
risk, broker, or execution behavior.

## Changes
- Activated the existing canonical WSGI composition boundary: Render now starts
  `gunicorn wsgi:app` instead of `gunicorn app:app`. `wsgi:app` currently resolves
  to the same Flask application through `engine.application_composition:create_app`.
- Upgraded the 65.3 dependency mapper to schema 65.4 and included all root-level
  runtime/support Python modules in static dependency reachability. This removes
  false orphan labels caused by dependencies routed through `apex_engines.py`.
- Added `engine/runtime_consolidation.py`, a conservative second-level audit over
  cleanup candidates. It checks tests, config, root support files, package
  sentinels, route ownership and compatibility state before suggesting action.
- Added `GET /api/runtime/consolidation` and made it part of the critical route
  audit. No module is automatically deleted in 65.4.
- Added explicit composition metadata to the Flask app config for future route
  extraction behind a stable production entry point.

## Safety policy
A static `ORPHANED` classification is not deletion authorization. 65.4 reports
`REVIEW_FOR_REMOVAL` only after secondary checks, and still sets
`safe_to_delete=false` pending manual dynamic-import/persistence review.

## Trading behavior
Unchanged.

## Validation result
- APEX 65.x stabilization tests: 26/26 PASS.
- Repository-wide Python compilation: PASS.
- All dashboard JavaScript syntax checks: PASS.
- Canonical dependency map after 65.4: 312 engine modules; 284 ACTIVE; 7 COMPATIBILITY; 4 DORMANT; 17 ORPHANED.
- Cleanup candidates reduced to 28 after root-support reachability correction.
- Second-level disposition: 18 protected/migration-required, 1 move-to-tests, 3 manual removal review, 0 automatic deletions.
- Monday critical: 12/12 present and ACTIVE.

Note: a full local WSGI import smoke test was not possible in the build container because Flask is not installed in that execution environment. The repository `requirements.txt` does declare Flask 3.0.3, and static/compile/regression validation passed.
