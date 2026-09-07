# APEX 69.0.2 — Flow Settlement Scheduler Closure

## Purpose
Close the historical flow-feature label lifecycle by making settlement an explicit responsibility of the dedicated scanner process rather than an incidental post-close branch in the legacy background scanner loop.

## Runtime behavior
- Scanner-owned `FlowSettlementScheduler` runs immediately after deployment/startup and then on a bounded cadence.
- Default cadence: 300 seconds (`APEX_FLOW_SETTLEMENT_SECONDS`).
- Default recovery window: 30 feature sessions (`APEX_FLOW_SETTLEMENT_MAX_SESSIONS`).
- Before 16:05 ET and on weekends, only prior sessions are eligible.
- After 16:05 ET on weekdays, the completed current session can also be retried.
- The legacy scanner-loop settlement branch is disabled by default when `APEX_FLOW_SETTLEMENT_SCHEDULER_ENABLED=true`.
- Settlement remains evidence-only: no synthetic excursion, MFE, MAE, cost basis, or label is fabricated.

## Observability
`/api/learning/evidence-lifecycle` now receives authoritative scanner heartbeat settlement telemetry under `families.flow_features.settlement`, including scheduler state and the complete `last_result` from `settle_pending_labels()`.

Diagnostics include sessions checked, sessions with unlabelled rows, pending vectors, labels written, missing feature vectors, missing excursion rows, missing MFE, missing cost basis, leakage rejections, skipped rows, and write failures.

## Guardrails
No trade-decision changes. No execution-authority changes. No automatic recalibration. No historical backfill fabrication. No label-requirement relaxation.

## Validation
101 targeted persistence, evidence lifecycle, calibration, attribution, feature-store and release regression tests passed. Flask-dependent route tests could not be executed in this container because Flask is not installed; route/source contracts were validated statically and modified modules compile successfully.
