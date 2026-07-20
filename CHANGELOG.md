# APEX 25.2 — Decision Outcome Forecasting Engine (CHANGELOG)

Sprint: 25.2 of the APEX 25.x Institutional Decision Intelligence Program.
Mode: SHADOW ONLY. `production_effect: NONE` on every response.

## Added
- `engine/decision_outcome_forecast_v252.py` — deterministic forecasting engine
  built on APEX 25.0 Decision Integrity. Projects expected path, magnitude,
  duration, MFE/MAE, target/invalidation zones, a reconciling 4-way scenario
  distribution, forecast quality, and expected grade. Includes look-ahead-safe
  historical analog integration, governed sqlite persistence, and a
  matured-only forecast evaluator.
- `engine/decision_outcome_forecast_v252_routes.py` — six canonical routes.
- `tests/test_decision_outcome_forecast_v252.py` — 18 engine/unit/determinism/
  degraded-evidence/look-ahead/persistence tests.
- `tests/test_decision_outcome_forecast_v252_routes.py` — 10 route tests.

## Modified
- `app.py` — fail-loud import + registration block for 25.2 (mirrors 25.0/25.1),
  wired to the existing `STATE["last_result"]` provider under `STATE_LOCK`.
- `engine/configuration_governance.py` — registered `APEX_DECISION_FORECAST_DB`
  in the authoritative env-var registry (category DATABASE, default
  `apex_decision_forecast.db`) so the production env-drift guard passes.

## Guarantees
- Deterministic: no randomness; identical snapshot -> identical forecast body.
- Shadow-only: never changes execution eligibility, never mutates production
  confidence, never submits orders, never overrides 25.0, never modifies weights.
- Look-ahead safe: analogs dated >= forecast `as_of` are excluded; the evaluator
  refuses to score before the horizon matures (HTTP 409 NOT_MATURED).
- Degraded critical evidence (missing/failed/stale) forces INSUFFICIENT_DATA/LOW;
  an unavailable source is never treated as neutral.
- Scenario probabilities always reconcile to exactly 100.
