# APEX 69.10.23 — Canonical Feature-to-P/L Observation Ownership Closure

## Purpose
Production 69.10.22 proved that canonical excursion persistence/readback and exact-owner enforcement are healthy while newly persisted settlement samples can remain `AWAITING_GENUINE_REAL_PL`. 69.10.23 makes the exact feature-to-genuine-P/L handoff durable and inspectable.

## Implementation
- Adds `flow_feature_pl_handoff_audit` to the canonical tracking database.
- Every genuine cluster P/L observation records whether the existing exact `(session_date, legacy_cluster_key, decision_time)` resolver found a persisted feature owner.
- Adds `feature_pl_handoff_health()` telemetry with total observations, exact owner found/missing counts, resolution percentage, direction breakdown, and latest handoff.
- Exposes the handoff telemetry under sample-excursion health/evidence lifecycle.
- Existing exact-owner success path remains unchanged: when the exact owner exists, the same canonical sample receives the genuine-P/L excursion.

## Guardrails
This release does not reconstruct sample IDs, perform fuzzy or nearest-time matching, attach P/L by direction/expiration/proximity, synthesize P/L or excursions, backfill historical evidence, change trade decisions, or change execution authority. Missing exact owners remain missing.

## Validation
- APEX 69.10.x lineage: 141/141 passed.
- Focused feature-store/writer, Flow P/L, historical-similarity, settlement-health, and scheduler suite: 212/212 passed.
- New 69.10.23 tests: 4/4 passed.
- Python compileall: passed.
