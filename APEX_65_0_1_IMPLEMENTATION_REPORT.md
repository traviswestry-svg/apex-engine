# APEX 65.0.1 — Canonical Route Ownership Hotfix

## Purpose
Resolve the three production duplicate route registrations detected by the APEX 65 runtime route audit after deployment.

## Fixed duplicate routes
- `GET /api/execution-intelligence/status`
  - Canonical owner retained: `engine/institutional_execution_intelligence_routes.py` (APEX 24.0)
  - Legacy duplicate removed: `engine/institutional_roadmap_routes.py` (APEX 15.4 compatibility surface)
- `GET /api/trade-management/status`
  - Canonical owner retained: `engine/execution_suite_v26x_routes.py` (APEX 26.5)
  - Legacy duplicate removed: `engine/institutional_roadmap_routes.py` (APEX 16.2 compatibility surface)
- `POST /api/trade-management/evaluate`
  - Canonical owner retained: `engine/execution_suite_v26x_routes.py` (APEX 26.5)
  - Legacy duplicate removed: `engine/institutional_roadmap_routes.py` (APEX 16.2 compatibility surface)

## Preserved compatibility surfaces
No persistence/history functionality was removed. The roadmap module still owns its unique legacy endpoints including `/api/trade-management/record`, `/api/trade-management/history`, and the non-conflicting execution-intelligence endpoints.

## Validation
- APEX 65 stabilization tests: 7/7 PASS
- Python compile: PASS
- Frontend/backend literal contract audit: 183 refs, 0 unresolved

## Expected production verification
After deployment, `GET /api/runtime/route-audit` should report:
- `status: HEALTHY`
- `duplicate_route_count: 0`
- `duplicates: []`
- `critical_missing: []`
- `auth_layer_available: true`
