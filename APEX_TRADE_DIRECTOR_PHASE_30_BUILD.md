# APEX Trade Director Phase 30

## Institutional Execution Certification & Production Readiness

Phase 30 adds a fail-closed execution certification layer. It normalizes order intent, validates pre-trade gates, creates sandbox-only cost previews, requires explicit human confirmation, reconciles internal and broker state, and exposes an emergency kill switch.

## Safety boundary

Phase 30 contains no live broker submission function. Confirmation certifies a preview only. Autonomous execution, live order placement, risk overrides, and credential mutation remain structurally disabled.

## Added

- `engine/trade_director_execution_certification.py`
- Execution Certification Center dashboard panel
- `/api/execution-certification/*` endpoints
- `tests/test_trade_director_phase30.py`

## Endpoints

- `GET /api/execution-certification/status`
- `GET /api/execution-certification/checks`
- `GET /api/execution-certification/broker-health`
- `GET /api/execution-certification/reconciliation`
- `GET /api/execution-certification/readiness`
- `POST /api/execution-certification/run`
- `POST /api/execution-certification/preview`
- `POST /api/execution-certification/confirm`
- `POST /api/execution-certification/cancel`
- `POST /api/execution-certification/reconcile`
- `POST /api/execution-certification/kill-switch`
