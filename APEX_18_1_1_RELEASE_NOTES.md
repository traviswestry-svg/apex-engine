# APEX 18.1.1 — Dynamic Position Sizing
Runtime: `11.0.9_DYNAMIC_POSITION_SIZING`

Adds advisory premium contract sizing bounded by canonical max loss, per-trade risk, remaining daily loss capacity, account risk, confidence, historical sample readiness, expectancy, and drift. Adds `GET /api/premium_discipline/position-sizing` and includes sizing in the command-center payload. It has no broker execution authority.
