# APEX 65.0 — Production Stabilization & Runtime Consolidation

## Scope
APEX 65.0 is a reliability-only build for Monday readiness. It adds no trading signal logic, scoring changes, broker automation changes, or strategy features.

## Changes

### 1. Canonical evidence route ownership
- Phase 31 Trade Director remains the owner of `GET /api/evidence/status`.
- The older institutional-roadmap status endpoint moved to `GET /api/evidence/legacy/status`.
- This prevents the legacy registrar from failing part-way through route registration because of a duplicate Flask rule.

### 2. Legacy command-center collision removed
- The inactive v24.5 command-center status route moved from `/api/command-center/status` to `/api/command-center/v245/status`.
- The canonical v26.9 command center retains `/api/command-center/status`.

### 3. Monday-critical Trade Director endpoints hardened
The following endpoints now use fail-soft behavior with cached fallback data:
- `GET /api/position/market-memory`
- `GET /api/position/cross-asset-intelligence`
- `GET /api/position/strategy-orchestration`

Responses distinguish `HEALTHY`, `DEGRADED`, `FAILED`, and `UNAVAILABLE`, expose whether fallback data was used, and log the underlying exception type without leaking exception text to clients.

Phase 13 enrichment inside Phase 14 is isolated so a cross-asset build failure does not automatically take down strategy orchestration.

### 4. Request correlation / observability
Every request receives:
- `X-APEX-Request-ID`
- `X-APEX-Duration-Ms`

HTTP 5xx responses are logged with request ID, method, path, status, and duration.

### 5. Runtime route audit
Added authenticated endpoint:
- `GET /api/runtime/route-audit`

It reports final runtime route count, duplicate method/path registrations, missing Monday-critical routes, auth-layer availability, version, and audit timestamp.

### 6. Static frontend/backend contract audit
Added:
- `tools/apex65_contract_audit.py`

Current result: **183 frontend API references, 838 backend literal route patterns, 0 unresolved literal frontend references.**

### 7. Regression tests
Added `tests/test_apex65_stabilization_static.py` covering route ownership, fail-soft guards, request diagnostics, and route-audit installation.

## Validation completed
- Python compile check passes for every changed Python file.
- Frontend/backend static contract audit passes with zero unresolved literal API references.
- Static APEX 65 regression tests pass.

## Deployment smoke checks
After deployment, verify:
1. `/health`
2. `/api/runtime/route-audit` => `status=HEALTHY`, `duplicate_route_count=0`, no `critical_missing`
3. `/api/position/market-memory`
4. `/api/position/cross-asset-intelligence`
5. `/api/position/strategy-orchestration`
6. `/api/evidence/status`
7. `/api/command-center/status`

For the three intelligence endpoints, `DEGRADED` with `fallback_used=true` is an acceptable fail-soft state during a downstream builder issue; an unexplained HTTP 500 is not.

## Next build
APEX 65.1 should centralize frontend API access/error handling and add a consolidated Monday-readiness diagnostics panel. Do not add trading features until 65.x stabilization is complete.
