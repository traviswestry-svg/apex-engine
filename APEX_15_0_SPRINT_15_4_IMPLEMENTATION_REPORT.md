# APEX 15.0 Sprint 15.4 — Institutional Execution Intelligence

## Purpose
Provide deterministic, immutable, offline analytics for completed trade execution without changing live broker behavior.

## Implemented
- `engine/institutional_execution_intelligence.py`
- Immutable execution records and aggregate analyses
- Entry slippage, entry quality, exit quality, profit capture, realized/available P&L, MFE/MAE proxy, hold duration, realized R, fees, and mistake diagnostics
- Flask APIs and dashboard
- Additive SQLite schema and governance audit events
- Safety contract preventing order submission, order mutation, policy mutation, or production effects

## Database tables
- `execution_intelligence_records`
- `execution_intelligence_analyses`

## APIs
- `GET /api/execution-intelligence/status`
- `POST /api/execution-intelligence/evaluate`
- `POST /api/execution-intelligence/records`
- `GET /api/execution-intelligence/records`
- `POST /api/execution-intelligence/analyze`
- `GET /api/execution-intelligence/dashboard`

## Dashboard
- `/apex_os/execution_intelligence`
- `/apex_os/institutional_execution_intelligence`

## Safety
`production_effect=NONE`; completed-trade analytics never place or modify orders and never update live execution policy automatically.
