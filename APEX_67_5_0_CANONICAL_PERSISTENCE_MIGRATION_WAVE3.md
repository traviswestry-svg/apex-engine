# APEX 67.5.0 — Canonical Persistence Migration Wave 3

## Objective

Extend the canonical SQLite connection policy into a deliberately bounded set of high-consequence execution, risk, and position-lifecycle stores. This release is a persistence-policy migration only.

## Migrated modules

- `engine/adaptive_trade_management.py`
- `engine/broker_synchronized_position_state.py`
- `engine/confirmation_gated_execution.py`
- `engine/execution_reality_slippage.py`
- `engine/portfolio_risk_intelligence.py`
- `engine/premium_portfolio_risk_governor.py`
- `engine/trade_lifecycle_intelligence.py`
- `engine/premium_execution_orchestrator.py`
- `engine/institutional_execution_intelligence.py`

Each migrated module now opens its existing database path through `engine.canonical_persistence.connect` rather than opening SQLite directly.

## Preserved contracts

67.5.0 does **not** change database paths, schemas, trading logic, model logic, risk rules, or execution authority. Existing per-store timeouts are preserved where they were explicitly specified. The migration remains staged; analytics, replay, research, reporting, and lower-consequence SQLite stores remain outside this wave.

## Guardrails

- No schema migration.
- No database relocation.
- No trading-logic change.
- No risk-rule change.
- No execution-authority change.
- Canonical persistence remains infrastructure with `decision_authority: none`.
