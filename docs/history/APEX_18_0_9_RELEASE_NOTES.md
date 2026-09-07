# APEX 18.0.9 — Institutional Premium Intelligence

Runtime: `11.0.7_INSTITUTIONAL_PREMIUM_INTELLIGENCE`

Adds a read-only portfolio-ranking layer above Premium Discipline. It evaluates all currently executable 0DTE credit structures—bull put spread, bear call spread, and iron condor—under one regime, eligibility, expected-value, direction-fit, and execution-quality model.

## New API

`GET /api/premium_discipline/intelligence`

## Governance

The engine is advisory only and has no broker execution authority. Iron butterflies, broken-wing butterflies, calendars, and diagonals are explicitly excluded until canonical pricing, fill-quality, and replay support exists.
