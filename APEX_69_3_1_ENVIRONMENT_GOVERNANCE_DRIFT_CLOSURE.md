# APEX 69.3.1 — Environment Governance Drift Closure

## Scope
Registers the four APEX 69.x runtime environment variables already used by the historical-evidence and flow-settlement runtime so production environment governance remains canonical.

## Registered variables
- `APEX_69_MARKET_MEMORY_CAPTURE_ENABLED` — boolean, default `true`
- `APEX_FLOW_SETTLEMENT_SCHEDULER_ENABLED` — boolean, default `true`
- `APEX_FLOW_SETTLEMENT_SECONDS` — integer, default `300`
- `APEX_FLOW_SETTLEMENT_MAX_SESSIONS` — integer, default `30`

## Guardrails
This patch changes no trade decisions, execution authority, feature definitions, label thresholds, settlement semantics, or learning policy. It only closes configuration-governance drift.
