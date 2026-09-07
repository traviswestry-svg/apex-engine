# APEX 65.3 — Canonical Runtime & Engine Dependency Map

## Objective
Create a machine-readable, production-safe map of the actual APEX runtime so future cleanup is based on code reachability and route/dashboard usage rather than filenames or assumptions.

## Changes
- Added `engine/runtime_dependency_map.py`.
- Added `GET /api/runtime/dependency-map`.
- Added the dependency-map endpoint to the critical route audit.
- Added an explicit Monday decision path from TradingView ingest through execution.
- Added feed-to-engine, engine-import, engine-to-route, and route-to-dashboard-consumer relationships.
- Added module classifications: `ACTIVE`, `COMPATIBILITY`, `DORMANT`, `ORPHANED`.
- Added a non-destructive cleanup queue. No module is automatically deleted by this build.
- Normalized closed-market Institutional Engines aggregate counts: standby engines now report `standby`, normalized `red: 0`, while preserving `raw_red` for diagnostics.

## Current static inventory
- Engine modules: 311
- Active: 282
- Compatibility: 7
- Dormant: 4
- Orphaned: 18
- Cleanup candidates: 29
- Monday-critical engines: 12
- Monday-critical missing: 0
- Monday-critical non-active: 0
- Dashboard route references observed: 184
- Static Flask route declarations observed: 854

These counts are code-graph inventory counts, not the live Flask route count. The production `/api/runtime/route-audit` remains authoritative for live registered routes.

## Monday decision path
1. TradingView / Pine -> `/tv_signal`
2. Institutional OS composition -> `/api/institutional_os`
3. Trade Director Market Memory -> `/api/position/market-memory`
4. Cross-Asset Intelligence -> `/api/position/cross-asset-intelligence`
5. Strategy Orchestration -> `/api/position/strategy-orchestration`
6. Institutional Evidence / Readiness -> `/api/evidence/status`
7. SPX execution gateway -> `/api/trade/spx/place-entry`

## Safety properties
- Static filesystem/AST introspection only.
- No network requests.
- No database mutation.
- No scanner start.
- No engine recomputation.
- No broker/execution calls.
- Result cached once per process.

## Validation
- APEX 65 regression tests: 21/21 PASS
- Repository Python compileall: PASS
- Dashboard JavaScript syntax: PASS

## Deployment checks
1. `/api/runtime/route-audit` should remain `HEALTHY` with zero duplicates/missing critical routes.
2. `/api/runtime/dependency-map` should return `status: HEALTHY`, no missing/non-active Monday-critical modules, and a populated `monday_decision_path`.
3. `/api/runtime/health` should continue to report closed-market engines as standby and `tradeable_runtime: false` when the session is closed.
