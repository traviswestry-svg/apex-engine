# APEX 69.0.1 — Historical Evidence Observability Patch

## Purpose
Close observability gaps discovered after APEX 69.0 deployment without changing trading decisions, execution authority, learning thresholds, or evidence policy.

## Changes
- `/api/learning/evidence-lifecycle` now treats the fresh scanner heartbeat as the authoritative runtime telemetry source.
- Web/Gunicorn-local runtime counters are preserved separately as `web_local_runtime` for diagnosis.
- Endpoint exposes scanner heartbeat freshness, PID, age, and runtime source.
- Flow-label settlement diagnostics now expose pending rows, vectors loaded, excursion keys/rows found, missing feature vectors, missing excursion rows, missing MFE, missing cost basis, leakage rejections, write failures, and labels created.
- Prior-session recovery aggregates the same reason-level diagnostics across historical unlabelled sessions.
- Flow settlement diagnostics are surfaced directly under `families.flow_features.settlement`.
- Release truth ratcheted to 69.0.1 while preserving all 68.x and 69.0 guardrails.

## Guardrails
- No synthetic evidence.
- No historical backfill fabrication.
- No automatic recalibration.
- No changes to trade decisions.
- No changes to execution authority.
- Human promotion remains required.
- Settlement semantics are unchanged; labels still require persisted excursion evidence.

## Validation
- 165 passed, 0 failed across targeted historical evidence, feature-store, decision attribution, dynamic-state calibration, persistence, and release-truth regression tests.
