# APEX 69.4.3 — Live Flow Excursion Invocation Closure

## Finding
Production telemetry after 69.4.2 showed decision attribution progressing, while flow excursion telemetry remained at `capture_attempts=0`, `sample_excursions=0`, and settlement correctly reported missing canonical excursion rows. The scanner and web service are separate processes, while flow-store readiness had been established indirectly through Flask route registration. The production scanner also executed flow P/L before feature persistence, leaving the live capture block upstream of canonical identity publication.

## Closure
69.4.3 makes the scanner-owned lifecycle explicit and ordered:

1. The dedicated scanner process explicitly initializes the feature and flow P/L stores.
2. The feature writer can defer excursion capture while preserving its previous default behavior for existing callers.
3. After a sealed feature row is persisted and its exact immutable `sample_id` is registered, the writer emits a private canonical capture target.
4. The scanner immediately invokes `capture_persisted_feature_excursions()` on those targets.
5. Subsequent scanner cycles for an existing sealed sample widen the same canonical MFE/MAE row using real marks.
6. Scanner heartbeat telemetry now publishes scanner-process store readiness and canonical excursion capture health.

## Guardrails preserved
- No synthetic P/L or depth evidence.
- No historical excursion backfill.
- No reconstruction of `sample_id` on the live capture path.
- No relaxation of settlement or label requirements.
- No decision or execution authority changes.
- No confidence-weighting or adaptive-promotion changes.
- Missing P/L remains missing and is counted observably.
- Existing feature-writer callers retain their prior synchronous capture behavior unless they explicitly request deferred scanner capture.
