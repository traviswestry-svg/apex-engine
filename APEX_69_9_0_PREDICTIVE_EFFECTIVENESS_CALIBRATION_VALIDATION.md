# APEX 69.9.0 — Predictive Effectiveness & Calibration Validation

## Purpose
Shift the post-69.8 learning program from evidence accumulation to read-only validation of predictive effectiveness and calibration structure.

## Added
- `/api/triggers/predictive-validation`
- Confidence-band outcome diagnostics.
- Blocker effectiveness diagnostics.
- Direction/source/trigger cohort diagnostics.
- Calibration bucket distribution and fragmentation diagnostics.
- Premium Discipline dashboard section for decision-quality validation.

## Authority
All 69.9.0 diagnostics are observational. They do not change trade decisions, confidence, thresholds, consensus weights, calibration activation, execution authority, or broker state.

## Calibration
Aggregate readiness is not treated as activation readiness. Existing per-bucket sample requirements, independence weighting, statistical integrity gates, and human approval/activation boundaries remain unchanged.

## Interpretation
Reported cohort differences are associations in persisted evidence and must not be interpreted as causal effects without further validation.
