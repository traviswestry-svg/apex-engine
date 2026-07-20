# APEX 25.1 — Institutional Reasoning Engine

## Added
- Ranked institutional evidence with health-aware weighting.
- Counter-thesis and contradiction analysis.
- Confidence waterfall from raw confidence to integrity-adjusted confidence.
- Historical-match summary and institutional story timeline.
- Advisory pre-trade grade.
- Four read-only Institutional Reasoning API endpoints.
- Mission Control reasoning group and drill-down.

## Guardrails
- Read-only and deterministic.
- Does not submit broker orders.
- Does not mutate production confidence.
- Failed, stale, or missing evidence receives no supportive weight.
