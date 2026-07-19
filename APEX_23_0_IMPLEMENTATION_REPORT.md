# APEX 23.0 — Institutional Trading Brain

## Release identity

- Application version: `16.0.0_INSTITUTIONAL_TRADING_BRAIN`
- Semantic version: `16.0.0`
- Schema: `apex.institutional_trading_brain.v1`
- Baseline: APEX 22.5 complete deployed repository

## Implemented capabilities

1. Hierarchical reasoning above the existing institutional decision suite.
2. Dynamic evidence weighting by market regime and session context.
3. Explicit bullish/bearish evidence scoring and net-score resolution.
4. Severity-ranked conflict detection and written resolution rationale.
5. Primary thesis, alternate scenario, confirmation, and invalidation rules.
6. Five-stage institutional thesis timeline.
7. Dormant-safe Market Memory confidence calibration hooks.
8. Point-in-time similarity filtering through the `before` parameter.
9. Explainability payload showing supporting evidence, conflicts, limitations, and rejected alternatives.
10. Mission Control 2.0 Trading Brain summary and drill-down.

## New APIs

- `GET /api/trading-brain/status`
- `GET /api/trading-brain/diagnostics`
- `GET /api/trading-brain/thesis`
- `GET /api/trading-brain/evidence`
- `GET /api/trading-brain/calibration`

All APIs are read-only.

## Safety model

APEX 23.0 does not place, preview, modify, or cancel broker orders. It does not change existing execution permissions, kill switches, or confirmation requirements. Dynamic weights are calculated at request time and are not automatically promoted into permanent production configuration. Market Memory calibration remains dormant or provisional until adequate graded history exists.
