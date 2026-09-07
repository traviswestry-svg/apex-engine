# APEX 65.6.1 — Preflight Integrity Hardening

## Objective
Close the highest-leverage gaps between static assembly checks and Monday tradeability while preserving a network-free, broker-safe default readiness endpoint.

## Implemented
- Added `APEX_65_6_READINESS_AUDIT.md` documenting the 65.6 findings and dispositions.
- Added Monday-critical import smoke using `importlib.import_module()` for all 12 critical engine modules.
  - Import-time exceptions are required `FAIL` blockers.
  - No engine evaluate/build function is invoked.
- Added local E*TRADE credential freshness telemetry.
  - Supports issued/refreshed/updated/expiry timestamps plus optional maximum-age policy.
  - Reports `FRESH`, `STALE`, `EXPIRING_SOON`, `EXPIRED`, `INVALID_METADATA`, or `UNKNOWN`.
  - Never returns credential/token values.
  - Never performs a broker/network probe.
- Changed intentional `ETRADE_ENABLE_TRADING=false` from `WARN` to informational `INFO` so clean closed-market preflight status is reachable.
- Missing required runtime-health components now fail loudly instead of degrading to a closed-market warning.
- Schema/stabilization identity advanced to `65.6.1`.

## Validation
- APEX 65.x regression tests: **43/43 PASS**
- `tests/test_apex65_6_monday_readiness.py`: **12/12 PASS**
- Repository-wide Python compilation: **PASS**
- Dashboard JavaScript syntax checks: **PASS**
- Local Monday-critical import smoke: **12/12 PASS**
- Trading/scoring/risk logic: unchanged
- Broker mutation behavior: unchanged
- Route count: unchanged (no new route added)
