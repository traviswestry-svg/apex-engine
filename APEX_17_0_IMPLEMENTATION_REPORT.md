# APEX 17.0 Implementation Report

## Release
APEX 17.0 — Institutional Autonomous Desk

## Purpose
Unify APEX intelligence, governance, execution, position management, reconciliation, grading, and learning into one immutable governed trade lifecycle.

## New engine
- `engine/institutional_autonomous_desk.py`

## Lifecycle states
MONITORING, SETUP_DETECTED, VALIDATING, BLOCKED, READY_FOR_PREVIEW, AWAITING_CONFIRMATION, AUTHORIZED, SUBMITTED, PARTIALLY_FILLED, FILLED, MANAGING, PROTECTING, EXIT_PENDING, CLOSED, RECONCILED, GRADED.

## Governance
- Deterministic transition map; invalid jumps are rejected.
- Tradeability, portfolio-risk, and broker-sync gates are mandatory before preview readiness.
- AUTHORIZED requires a named human confirmer, confirmation ID, and explicit acknowledgement.
- SUBMITTED requires a broker order ID.
- CLOSED and RECONCILED require broker-flat evidence.
- Automatic order submission and broker mutation remain disabled.

## Persistence
- `autonomous_desk_trades`
- `autonomous_desk_events`
- `autonomous_desk_artifacts`

All records carry schema version, engine version, and SHA-256 integrity hashes.

## APIs
- `GET /api/autonomous-desk/status`
- `POST /api/autonomous-desk/trades`
- `POST /api/autonomous-desk/trades/<desk_trade_id>/transition`
- `POST /api/autonomous-desk/trades/<desk_trade_id>/artifacts`
- `GET /api/autonomous-desk/trades/<desk_trade_id>`
- `GET /api/autonomous-desk/history`
- `GET /api/autonomous-desk/dashboard`

## Mission Control
Mission Control now includes `institutional_autonomous_desk`, and the Institutional Trading Desk page displays active governed trade lifecycles.
