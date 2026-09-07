# APEX 65.2 — Runtime Health & Diagnostics Consolidation

## Scope
Production reliability/observability only. No signal, scoring, sizing, risk, strategy selection, broker, or order semantics changed.

## Implemented
- Added `engine/runtime_health.py`, a pure canonical health aggregator with standardized states: `HEALTHY`, `DEGRADED`, `STALE`, `UNAVAILABLE`, `DISABLED`, `FAILED`.
- Added authenticated `GET /api/runtime/health` as the canonical runtime diagnostics endpoint.
- Runtime health now consolidates authentication, route integrity, scanner/freshness, market-data sources, institutional engine health, and critical Trade Director intelligence health.
- Added in-process health telemetry for Market Memory, Cross-Asset Intelligence, and Strategy Orchestration. Diagnostics read the latest outcome without invoking/recomputing those engines.
- Critical intelligence failures record fallback usage, error type, timestamp, and state.
- Added weekend/closed-session truth handling so scheduled idle is not falsely reported as a production failure.
- Added `tradeable_runtime`, `blockers`, and `warnings` to make hard failures distinct from degraded/stale conditions.
- Added `/api/runtime/health` to the 65.x critical route audit.
- Added a Trade Director runtime-health status line with issue count and tooltip details.
- Added an Institutional OS runtime-health badge.
- Added `ApexAPI.runtimeHealth()` to the shared frontend reliability client.

## Safety
- The diagnostics endpoint performs no external network calls.
- The diagnostics endpoint does not launch scans or evaluate trading engines.
- No POST/execution retry behavior was introduced.
- No trading decision logic was changed.

## Validation
- APEX 65.x regression suite: 15/15 PASS.
- `app.py` and engine Python compilation: PASS.
- `static/js/apex_api.js`: syntax PASS.
- `static/js/apex_os.js`: syntax PASS.
