# APEX 18.2.0–18.2.2 Release Notes

Final runtime: `11.0.18_TRADE_LIFECYCLE_INTELLIGENCE`

## 18.2.0 — Institutional Learning Engine

Adds governed learning samples, low-cardinality market fingerprints, outcome grading, regime/strategy expectancy analysis, readiness controls, similar-pattern retrieval, and immutable learning-run records. Learning output is advisory and cannot alter active trading policy automatically.

## 18.2.1 — Decision Narrative

Adds a deterministic explanation layer combining Premium Discipline, Institutional Premium Intelligence, Portfolio Optimization, Execution Reality, Portfolio Risk Governor, and Institutional Learning evidence into a single headline, summary, evidence list, warnings, and blockers.

## 18.2.2 — Trade Lifecycle Intelligence

Adds advisory post-entry monitoring for thesis validity, short-strike breaches, execution deterioration, regime changes, profit capture, loss containment, and expiration proximity. Supported lifecycle recommendations are `HOLD`, `PROTECT`, `REDUCE`, `TAKE_PROFIT`, and `EXIT`. The module never submits or modifies broker orders.

## New APIs

- `GET /api/premium_discipline/learning`
- `GET|POST /api/premium_discipline/learning/samples`
- `POST /api/premium_discipline/learning/grade`
- `GET /api/premium_discipline/decision-narrative`
- `GET|POST /api/premium_discipline/trade-lifecycle`

The Premium Discipline Command Center now includes `institutional_learning`, `decision_narrative`, and `trade_lifecycle_intelligence`.
