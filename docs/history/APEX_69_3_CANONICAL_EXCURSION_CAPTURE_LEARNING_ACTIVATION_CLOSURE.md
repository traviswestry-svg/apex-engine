# APEX 69.3.0 — Canonical Excursion Capture & Learning Activation Closure

## Objective
Close the prospective flow-learning gap where immutable feature vectors were persisted and settlement ran, but no canonical sample-scoped excursion evidence was being created.

## Changes
- Canonical excursion rows are keyed only by immutable feature `sample_id`.
- A canonical excursion row is created only after the matching feature sample is confirmed persisted.
- Existing sealed samples widen the same MFE/MAE envelope on each real P/L observation.
- Missing real P/L is counted as missing evidence; no synthetic excursion is created.
- Orphan excursion rows are prevented when a feature cannot be frozen (for example, no valid replay frame).
- Durable cross-process capture telemetry is persisted in `flow_excursion_capture_audit`.
- `/api/learning/evidence-lifecycle` exposes the telemetry under `families.flow_features.excursion_linkage.capture`.

## Capture telemetry
- `capture_attempts`
- `excursions_inserted`
- `excursions_updated`
- `missing_feature_sample`
- `missing_pl`
- `capture_errors`
- `last_attempt_at`
- `last_success_at`
- `last_sample_id`

## Guardrails
- No synthetic historical backfill.
- No relaxation of flow-label requirements.
- No trade-decision changes.
- No execution-authority changes.
- Legacy coarse cluster keys remain lineage only and cannot select a label.

## Validation
- Focused canonical excursion/feature/settlement regression: 44 passed.
- Expanded APEX 68.5→69.3 evidence/feature/persistence regression: 185 passed, 0 failed.
- Full local collection is blocked by the validation container's missing Flask dependency; GitHub CI should run the complete suite in its normal environment.
