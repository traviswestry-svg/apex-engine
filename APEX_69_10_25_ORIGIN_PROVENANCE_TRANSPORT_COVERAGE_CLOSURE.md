# APEX 69.10.25 — Origin Provenance Transport Coverage Closure

## Objective

Close the dominant 69.10.24 production transport-coverage gap without relaxing canonical ownership. Production showed 2,497 provenance-audited P/L handoffs, with 148 carrying origin provenance and 2,349 missing it. At the same time, the September 30 settlement cohort was healthy: 1,543 exact requested/excursion matches produced 1,543 labels with zero ownership-integrity failures.

69.10.25 therefore leaves settlement, label eligibility, genuine-P/L requirements, and exact registered-owner verification unchanged. It changes only how immutable origin provenance survives a rebuilt cluster whose membership has expanded.

## Root Cause Addressed

69.10.24 published immutable bindings from originating market-event IDs to the successfully persisted canonical feature sample. Its resolver required every event ID in a later rebuilt cluster to have a binding and required every binding to name the same origin tuple.

That rule was too strict for a continuing cluster that retained directly bound origin events but later gained new events. The new events had no binding yet, so the entire later observation was classified as provenance-missing even though direct ancestry to the original persisted sample remained present.

## 69.10.25 Transport Rule

69.10.25 resolves origin provenance only from direct event ancestry:

1. `FULL_EXACT_BINDING`
   - Every current event ID is bound.
   - Every bound event names the same immutable origin tuple.
   - Ownership transport is authorized.

2. `PARTIAL_CONSISTENT_BINDING`
   - At least one current event ID is directly bound to an immutable persisted origin.
   - One or more newly-added current event IDs are unbound.
   - Every bound event names the same immutable origin tuple.
   - Ownership transport is authorized.
   - Unbound events do not contribute to owner selection.

3. `NO_BOUND_EVENTS`
   - No direct event ancestry exists.
   - Fail closed. No owner is assigned.

4. `NO_EVENT_IDS`
   - No transport identity is available.
   - Fail closed.

5. `CONFLICTING_BOUND_ORIGINS`
   - Current bound events name more than one persisted origin.
   - Fail closed. No attempt is made to choose one.

6. `STORE_NOT_READY` / `RESOLVER_ERROR`
   - Fail closed and expose the condition diagnostically.

## What This Does Not Do

69.10.25 does not assign ownership by ticker, expiration, option type, direction, cluster key similarity, timestamp proximity, nearest sample, latest sample, regenerated IDs, or other semantic/fuzzy matching.

A partial consistent binding is not partial market-attribute matching. It is direct ancestry: at least one actual member event in the continuing observation carries the exact immutable origin binding created at the successful feature persistence boundary, and all directly bound members agree.

## Exact Owner Gate Remains

Transport resolution is not sufficient authority by itself. Before a canonical excursion write, the resolved origin tuple is still verified against the registered canonical identity map:

- `sample_id`
- `session_date`
- `legacy_cluster_key`
- `decision_time`

Any tuple mismatch refuses the write.

## Genuine P/L Requirement Remains

The P/L pipeline still requires genuine observed P/L. 69.10.25 does not synthesize marks, MFE, MAE, cost basis, historical quotes, or zero-P/L outcomes.

## New Coverage Audit

69.10.25 adds durable reason-coded transport observability through `flow_feature_origin_transport_audit` and `feature_origin_transport_coverage_health()`.

Production can now distinguish:

- `full_exact_bindings`
- `partial_consistent_bindings`
- `no_event_ids`
- `no_bound_events`
- `conflicting_bound_origins`
- `store_not_ready`
- `resolver_errors`
- `transport_owner_resolved`
- `transport_owner_missing`
- `transport_resolution_pct`
- `observations_with_any_bound_event`
- `bound_events`
- `unbound_events`

The per-session feature-origin audit now includes the same transport-coverage breakdown.

## Guardrails

- direct continuing event ancestry only
- exact registered owner still required
- genuine P/L still required
- conflicting origins fail closed
- no market-attribute matching
- no timestamp-proximity matching
- no fuzzy matching
- no canonical identity reconstruction
- no latest-owner substitution
- no synthetic P/L
- no synthetic excursions
- no historical backfill
- no trade-decision changes
- no execution authority
- no automatic promotion
- settlement semantics unchanged

## Release Metadata

- APEX: `69.10.25`
- Build: `11.0.1`
- Build name: `Origin Provenance Transport Coverage Closure`
- Database schema: `8`
- Transport identity basis: `DIRECT_CONTINUING_EVENT_ANCESTRY_ONLY`
