# APEX 65.6 — Monday Readiness Audit

## Objective
Review the 65.6 Monday-readiness contract for gaps between **assembled** and **tradeable**, while preserving the endpoint's weekend safety contract: no market-data probe, no broker preview, no order submission, and no trading-engine evaluation.

## Findings

### 1. Disarmed live-execution switch polluted readiness status
`ETRADE_ENABLE_TRADING=false` was intentionally safe during weekend validation, but 65.6 represented it as `WARN`. That made `PREFLIGHT_PASS_LIVE_VALIDATION_PENDING` effectively unreachable during the normal preview-only weekend posture because an intentional kill-switch state always forced `READY_WITH_WARNINGS`.

**65.6.1 disposition:** corrected. A deliberately disarmed execution switch is now an informational state (`INFO`) with `execution_armed=false`; it remains visible but does not count as a readiness warning or blocker.

### 2. Live-cycle component lookup depended on display strings
65.6 resolved runtime-health components by exact labels such as `Scanner / Freshness`, `Institutional Engines`, and `Trade Director Intelligence`. A future label rename could cause the lookup to miss and, during a closed session, previously degrade into `WARN` instead of failing loudly.

**65.6.1 disposition:** hardened. Missing required runtime-health components now return `FAIL` in both closed- and open-market modes. Stable machine IDs remain the preferred future contract, but a display-name drift can no longer silently become a warning.

### 3. Credential presence did not prove credential freshness
65.6 verified that the required E*TRADE credential fields were populated, but it did not distinguish a recently refreshed token from stale/expired local token metadata.

**65.6.1 disposition:** implemented local credential-freshness telemetry in `engine/monday_readiness.py`. The check is network-free and never exposes token values. It supports local metadata supplied by the application layer:

- `ETRADE_OAUTH_TOKEN_ISSUED_AT`
- `ETRADE_OAUTH_TOKEN_REFRESHED_AT` (preferred) or `ETRADE_OAUTH_TOKEN_UPDATED_AT`
- `ETRADE_OAUTH_TOKEN_EXPIRES_AT`
- `ETRADE_OAUTH_TOKEN_MAX_AGE_SECONDS` (optional policy threshold)
- `ETRADE_OAUTH_TOKEN_WARN_BEFORE_EXPIRY_SECONDS` (default 7200 seconds)

The readiness output reports `FRESH`, `STALE`, `EXPIRING_SOON`, `EXPIRED`, `INVALID_METADATA`, or `UNKNOWN`. Stale/expiry conditions are `WARN`, not hard blockers. If no local timestamp metadata is configured, freshness is explicitly `UNKNOWN` and no freshness assertion is made.

### 4. Static dependency reachability did not prove importability
The dependency map could classify a Monday-critical module as present/active even if production packaging or an import-time dependency would raise `ImportError`/`ModuleNotFoundError` at runtime.

**65.6.1 disposition:** implemented an `importlib.import_module()` smoke test for all 12 Monday-critical engine modules. Import errors and other import-time exceptions are captured per module and produce a required `FAIL`. The already-running `app` root is not re-imported as an engine smoke target because successful execution of the readiness route already proves the application root loaded.

## Safety contract after 65.6.1
The endpoint still performs no explicit network or broker operation:

- `network_io_performed: false`
- `broker_preview_invoked: false`
- `broker_order_submitted: false`
- `engines_invoked: false`
- `imports_performed: true`

The import smoke executes Python module import only; it does not call engine build/evaluate functions.

## Expected closed-market semantics
A healthy preview-only weekend posture with no actual warnings can now report:

```json
{
  "status": "PREFLIGHT_PASS_LIVE_VALIDATION_PENDING",
  "monday_ready": true,
  "validation_mode": "STATIC_PREFLIGHT",
  "live_validation_pending": true,
  "execution_mode": "PREVIEW_ONLY"
}
```

A stale/expiring credential metadata condition remains visible as `READY_WITH_WARNINGS`, while any critical-module import failure produces `BLOCKED`.

## Remaining gap
Credential freshness is only as strong as the locally supplied timestamp/expiry metadata. An authenticated broker read remains intentionally out of scope for the default endpoint. If a future `probe=true` mode is added, it must remain opt-in and must not submit/preview orders.
