# APEX Trade Director Phase 10 — Broker Execution Control Layer

## Scope
Phase 10 converts a current, acknowledged Phase 9 execution-readiness preview into a confirmation-gated E*TRADE order workflow. It is sandbox-first and fail-closed.

## Added
- Phase 10 execution-control engine and state machine.
- Operating modes: `DISABLED`, `PAPER`, `SANDBOX`, `LIVE_CONFIRMATION`.
- Exact-current-preview validation and stale-preview rejection.
- E*TRADE broker preview preparation using the existing adapter.
- Exact confirmation phrase and token validation before submission.
- Order states: `AWAITING_CONFIRMATION`, `SUBMITTING`, `ACCEPTED`, `FILLED`, `REJECTED`, `UNKNOWN`, and `RECONCILIATION_REQUIRED`.
- Single-flight protection against overlapping unresolved management orders.
- Broker-position reconciliation after submission.
- Phase 5 timeline and Phase 10 audit integration.
- Phase 10 dashboard panel on `/assistant`.

## Endpoints
- `GET /api/position/execution-control`
- `POST /api/position/execution-control/prepare`
- `POST /api/position/execution-control/confirm`
- `POST /api/position/execution-control/reconcile`

## Configuration
```text
APEX_TD10_MODE=DISABLED|PAPER|SANDBOX|LIVE_CONFIRMATION
APEX_TD10_ALLOW_LIVE=false
ETRADE_ENV=sandbox|production
ETRADE_ENABLE_TRADING=false|true
ETRADE_CONSUMER_KEY=...
ETRADE_CONSUMER_SECRET=...
ETRADE_OAUTH_TOKEN=...
ETRADE_OAUTH_TOKEN_SECRET=...
ETRADE_ACCOUNT_ID_KEY=...
```

Defaults remain disabled. Live confirmation additionally requires `APEX_TD10_ALLOW_LIVE=true`, `ETRADE_ENV=production`, complete credentials, the adapter trading kill switch, a current Phase 9 acknowledgement, and exact user confirmation.

## Validation
- `python -m py_compile app.py engine/trade_director_execution_control.py`
- Assistant JavaScript passed `node --check`.
- 60 existing Active Trade Director tests passed.
- Phase 10 policy, order-intent, exact-confirmation, stale-preview, and reconciliation smoke tests passed.
- Flask route smoke testing was not executable in the build container because Flask is not installed there; the repository requirements retain the application runtime dependency.

## Safety
No broker request occurs during startup or normal monitoring. The preview, submission, and reconciliation calls occur only after explicit user actions. The system refuses stale previews, unresolved-order overlap, unacknowledged Phase 9 previews, disabled modes, missing contract data, missing credentials, environment mismatches, and unarmed live execution.
