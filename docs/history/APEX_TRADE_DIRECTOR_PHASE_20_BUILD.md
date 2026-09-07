# APEX Trade Director Phase 20 — Institutional Decision Engine

## Purpose
Phase 20 converts the Phase 19 evidence committee into a governed decision lifecycle. It determines whether an idea should remain under observation, await validation, become conditionally authorized, or proceed only to the existing broker-preview and exact-confirmation workflow.

## New module
- `engine/trade_director_institutional_decision_engine.py`

## Authorization states
- `OBSERVE`
- `AWAITING_VALIDATION`
- `CONDITIONALLY_AUTHORIZED`
- `AUTHORIZED_FOR_PREVIEW`
- `DECISION_BLOCKED`

## Capabilities
- Deterministic decision IDs
- Pre-trade authorization checklist
- Committee consensus and evidence-coverage validation
- Session, strategy, contract, execution, timeframe, and flow gates
- Direction-specific invalidation rules
- Immediate defensive downgrades
- Stable-repeat requirement for less-defensive promotion
- Decision accountability metadata
- Preview-only authorization payload

## API
- `GET /api/position/institutional-decision-engine`
- `POST /api/position/institutional-decision-engine`

POST accepts optional normalized `context`/`evidence` and `prior` state for deterministic testing. It performs no provider or broker request.

## Dashboard
Adds the **Institutional Decision Engine** panel with:
- Authorization state
- Decision ID
- Governed action
- Contract, quantity, and limit context
- Authorization checklist
- Invalidation rules
- Hard blockers
- Stability state
- Exact-confirmation and broker-execution status

## Safety guarantees
Phase 20:
- cannot place, cancel, replace, or modify an order
- cannot contact E*TRADE or another broker
- cannot bypass Phase 9 risk controls
- cannot bypass Phase 10 exact confirmation
- cannot weaken Phase 16 execution safeguards
- cannot override session lockouts or upstream `STAND_DOWN`
- adds no startup worker or provider fan-out
- requires no new environment variables

## Validation
- Python compilation passed
- Dashboard JavaScript syntax passed
- Phase 20 authorization tests passed
- Phase 13–18 regression tests passed
- 28 targeted tests passed
