# APEX 25.3 — Adaptive Confidence Calibration Engine (CHANGELOG)

Sprint 25.3 of the APEX 25.x Institutional Decision Intelligence Program.
Mode: SHADOW ONLY. `production_effect: NONE` on every response.
Built on the completed 25.2 delta (assumes 25.0/25.1/25.2 deployed).

## Added
- `engine/adaptive_confidence_calibration_v253.py` — deterministic calibration
  engine producing the 25.x confidence-layer stack (raw -> integrity-adjusted ->
  historical -> regime-adjusted -> execution -> final_calibrated), each capped by
  the APEX 25.0 integrity ceiling. Empirical bucketed calibration with Bayesian
  shrinkage and hierarchical fallback (direction+regime+bucket -> regime+bucket
  -> bucket -> global prior), reliability metrics (Brier, ECE, max calibration
  error, false-confidence / underconfidence rates), drift detection, conservative
  confidence caps, and a governed (never-auto) promotion evaluator.
- `engine/adaptive_confidence_calibration_v253_routes.py` — six canonical routes.
- `tests/test_adaptive_confidence_calibration_v253.py` — 18 engine tests.
- `tests/test_adaptive_confidence_calibration_v253_routes.py` — 8 route tests.

## Modified
- `app.py` — fail-loud import + registration for 25.3 (mirrors 25.0-25.2),
  wired to `STATE["last_result"]` under `STATE_LOCK`.
- `engine/configuration_governance.py` — registered two governed feature flags:
  `APEX_CALIBRATION_PRODUCTION_ENABLED` and `APEX_CALIBRATION_PROMOTION_APPROVED`
  (both default false, safety-critical).

## Reuse (no duplication)
- Historical outcomes are read from the existing APEX 23.4 store
  (`apex_learning_outcomes_v234`) via `continuous_learning_calibration_v234._rows`.
  No new outcome-recording pipeline or database was created. History may also be
  supplied inline (`calibration_history`) for deterministic evaluation.

## Guarantees
- No calibrated layer ever exceeds the 25.0 integrity ceiling (asserted in code
  and tested).
- Small samples shrink toward broader groups then a global prior; fallback level,
  effective sample size, and shrinkage amount are always reported.
- Shadow-only: production confidence is never mutated; promotion never auto-fires
  and requires both a production flag and explicit operator approval.
- Deterministic given identical history.
