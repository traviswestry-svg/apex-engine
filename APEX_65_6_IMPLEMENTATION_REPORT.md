# APEX 65.6 — Monday Readiness & Critical-Path Validation

## Objective
Add a single, side-effect-free Monday preflight that answers whether the APEX SPX decision/execution path is structurally ready without invoking live engines, making network calls, previewing an order, or submitting an order.

## Added
- `engine/monday_readiness.py`
  - Pure readiness aggregator.
  - Validates runtime foundation, Monday-critical dependency graph, TradingView webhook secret, E*TRADE credential completeness, critical route contract, scanner/engine/Trade Director telemetry, and execution-mode state.
  - Distinguishes `PASS`, `STANDBY`, `WARN`, and `FAIL`.
  - Closed-market checks return `STATIC_PREFLIGHT` and preserve market-dependent checks as `STANDBY` rather than false failures.
  - `ETRADE_ENABLE_TRADING=false` is a warning, not a blocker, because preview/safety validation remains available while live mutation stays disarmed.
- `GET /api/runtime/monday-readiness`
  - Aggregates existing runtime telemetry and static route/dependency/config facts only.
  - Never invokes POST endpoints or broker actions.
  - Reports `monday_ready`, `validation_mode`, `live_validation_pending`, `execution_mode`, blockers, warnings, summary counts, and detailed checks.
- `tests/test_apex65_6_monday_readiness.py`
  - Closed-market preflight behavior.
  - Missing route, webhook secret, broker credentials, and critical-engine blocking behavior.
  - Market-open behavior and live-trading kill-switch warning semantics.

## Critical path contract checked
1. `POST /tv_signal`
2. `GET /api/position/market-memory`
3. `GET /api/position/cross-asset-intelligence`
4. `GET /api/position/strategy-orchestration`
5. `GET /api/evidence/status`
6. `GET /api/position/execution-readiness`
7. `GET /api/trade/spx/recommended-contracts`
8. `POST /api/trade/spx/preview-entry`
9. `POST /api/trade/spx/place-entry` (presence only; never invoked)

## Safety guarantees
The readiness endpoint records and guarantees:
- `network_io_performed: false`
- `engines_invoked: false`
- `broker_preview_invoked: false`
- `broker_order_submitted: false`

## Build identity
`engine.application_composition` stabilization identity advanced to `65.6`.

## Validation
- APEX 65.x regression tests: **37/37 PASS**
- Repository-wide Python compilation: **PASS**
- Dashboard JavaScript syntax checks: **PASS**
- Trading logic: unchanged
- Signal/scoring logic: unchanged
- Risk logic: unchanged
- Broker mutation behavior: unchanged

## Expected production route count
65.5 reported 880 method/routes. 65.6 adds one GET route, so the expected count is approximately **881**.
