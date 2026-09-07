# APEX 65.2.1 — Runtime State Semantics Hotfix

## Scope
Narrow diagnostics-only hotfix. No trading, signal, scoring, risk, order, or broker execution logic changed.

## Changes
- Added `runtime_ready` as the infrastructure/critical-path readiness truth.
- `tradeable_runtime` now requires `MARKET_OPEN` plus a fully HEALTHY required runtime.
- Added `tradeability_reason` (`READY`, `MARKET_CLOSED`, `RUNTIME_DEGRADED`, `RUNTIME_BLOCKED`).
- Added top-level `session` to `/api/runtime/health` output.
- Scheduled-idle engine rows that previously displayed `RED` are exposed as `STANDBY` when engines are not expected to be live.
- Preserved the underlying engine value in `raw_status` for diagnostics/auditability.
- Added explicit standby reason text when the market is closed and no live scan is required.

## Validation
- APEX 65.x stabilization/frontend/runtime regression subset: 18/18 PASS.
- Python compileall: PASS.
- Dashboard JavaScript syntax validation: PASS.
