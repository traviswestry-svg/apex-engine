# APEX 10 API Registration Fix

## Root cause
The Sprint 1-8 route modules existed in the repository but were never imported or registered in the production Flask `app` object. Render correctly started `gunicorn app:app`, so `/health` worked while the APEX 10 endpoints returned HTTP 404.

## Changes
- Registered provenance routes.
- Registered historical similarity routes.
- Registered learning/calibration routes.
- Registered dashboard evidence route.
- Registered institutional state, evidence graph, decision trace, and market story routes.
- Registered production readiness and metrics routes.
- Added a capability provider for honest readiness reporting.
- Updated the application version from `9.5.1_FEATURE_STORE_WRITER` to `10.0.0_PRODUCTION_HARDENED`.
- Added a regression test that verifies all APEX 10 URLs exist on the production app.
- Removed orphaned duplicate `engine/contracts.py` and `engine/persistence.py`, as required by the repository architecture guard.

## Validation
Focused deployment/API tests: 5 passed.
Full suite: 627 passed, 1 failed.
The remaining failure is an existing order-dependent range-intelligence database-isolation test; it passes when run alone and is unrelated to route registration.
