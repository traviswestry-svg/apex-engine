# APEX 69.10.25 Build Report

## Release

**Version:** 69.10.25  
**Build name:** Origin Provenance Transport Coverage Closure  
**Database schema:** 8  
**Starting point:** APEX 69.10.24 reconstructed from the authoritative 69.10.23 repository plus the completed 69.10.24 changed-files package.

## Production Evidence Driving This Build

The September 30 production telemetry showed that settlement itself no longer required another relaxation or matching change:

- September 30 pending feature samples: 1,713
- registered identities: 1,707
- requested with exact excursion: 1,543
- canonical excursion rows found: 1,543
- labels created: 1,543
- ownership integrity failures: 0
- exact requested/excursion overlap: 90.0759%

However, the 69.10.24 origin path showed:

- P/L handoff observations: 2,497
- origin provenance present: 148
- origin provenance missing: 2,349
- owner validated: 148
- owner validation failed: 0
- provenance resolution: 5.93%

This made provenance transport coverage—not settlement—the dominant remaining target.

## Source Trace and Root Cause

The audited path is:

1. `engine/feature_store_writer.py`
   - persists the canonical feature sample;
   - re-reads it by exact `sample_id`;
   - calls `flow_pl_store.register_sample_identity(...)`;
   - publishes originating `member_event_ids` into immutable origin bindings only after successful persistence.

2. Later scans rebuild clusters from market events in `engine/flow_clusters.py`.

3. `engine/flow_pl_pipeline.py` receives the rebuilt cluster and genuine aggregate P/L.

4. APEX 69.10.24 called `resolve_feature_origin_provenance()` with the rebuilt cluster's current `member_event_ids`.

5. The 69.10.24 resolver required every current event ID to already be bound to one identical persisted origin.

6. When a continuing cluster retained bound originating events but gained one or more new unbound events, the resolver returned no provenance for the entire P/L observation.

The implementation therefore had a deterministic ancestry signal that was being discarded by an all-members-bound requirement.

## Implementation

### 1. Reason-coded transport resolver

Added `resolve_feature_origin_transport()` in `engine/flow_pl_store.py`.

It returns one of:

- `FULL_EXACT_BINDING`
- `PARTIAL_CONSISTENT_BINDING`
- `NO_EVENT_IDS`
- `NO_BOUND_EVENTS`
- `CONFLICTING_BOUND_ORIGINS`
- `STORE_NOT_READY`
- `RESOLVER_ERROR`

`PARTIAL_CONSISTENT_BINDING` is authorized only when at least one current member event is directly bound and every bound current event names the exact same immutable origin tuple. Unbound current members are ignored for owner selection.

### 2. Fail-closed conflict handling

If two bound current events name different origin tuples, no origin is returned and no canonical excursion ownership write is permitted.

### 3. Existing exact owner validation preserved

After transport resolution, `verify_sample_identity_owner()` still verifies the complete registered tuple before any sample excursion write.

### 4. Genuine P/L gate preserved

The existing `record_sample_excursion()` genuine-P/L requirement remains unchanged.

### 5. Durable transport coverage telemetry

Added table:

`flow_feature_origin_transport_audit`

and health surface:

`feature_origin_transport_coverage_health()`

The health output provides counts for exact, partial-consistent, missing, conflict, and error paths and reports the resulting transport resolution percentage.

### 6. Per-session audit extended

`feature_origin_session_audit(session_date)` now includes `transport_coverage` for that exact session.

### 7. Runtime health exposure

The flow excursion-linkage health payload now exposes `origin_transport_coverage` alongside the 69.10.24 `feature_origin_provenance` metrics.

### 8. Settlement unchanged

No settlement matching logic, exact-ID semantics, label eligibility rule, actionability gate, or execution authority was altered.

## Tests

### Dedicated 69.10.25 tests

Command:

`pytest -q tests/test_apex_69_10_25_origin_provenance_transport_coverage_closure.py`

Result:

**9 passed**

The dedicated suite proves:

- release truth and capability declaration;
- full exact event binding remains authorized;
- partial consistent direct ancestry closes the newly-added-member transport gap;
- no-bound-event observations fail closed;
- observations with no event IDs fail closed;
- conflicting bound origins fail closed;
- exact registered-owner verification remains mandatory;
- telemetry distinguishes transport reasons;
- direction evolution does not mutate the original owner.

### Full APEX 69.10.x lineage

Command:

`pytest -q tests/test_apex_69_10_*.py`

Result:

**157 passed**

### Relevant feature-store / flow-P&L / excursion / settlement / evidence-lifecycle / identity suites

The Flask-dependent API test was excluded because Flask is not installed in this execution environment.

Result:

**311 passed**

### Environment dependency limitation

`tests/test_feature_store_api.py` could not collect:

`ModuleNotFoundError: No module named 'flask'`

This is reported as an environment dependency limitation, not a product-code failure.

### Compile validation

`python -m compileall -q engine`

Result: **passed**

## Production Acceptance Metrics

After deployment, compare new forward P/L observations using:

- `origin_transport_coverage.transport_observations`
- `full_exact_bindings`
- `partial_consistent_bindings`
- `no_bound_events`
- `conflicting_bound_origins`
- `transport_owner_resolved`
- `transport_owner_missing`
- `transport_resolution_pct`
- `feature_origin_provenance.origin_provenance_present`
- `origin_owner_validated`
- `origin_owner_validation_failed`
- `origin_owned_excursion_writes`
- `origin_owned_excursion_updates`
- `ownership_integrity_failures`
- `readback_missing`
- `readback_identity_mismatch`

The key question is whether a material portion of the former 2,349 provenance-missing observations now classify as `PARTIAL_CONSISTENT_BINDING` and validate successfully.

## Remaining Production-Only Uncertainty

Local tests prove the transport semantics but cannot determine the real production distribution of missing cases. Production may show that many missing observations contain no bound ancestor events at all. Those cases will remain `NO_BOUND_EVENTS` and will not receive an owner.

The current single-binding-per-event registration model may also expose a smaller continuity issue if the same raw event legitimately participates in multiple separately persisted canonical feature samples. 69.10.25 intentionally does not choose among multiple possible owners by recency, overlap score, cluster similarity, or other inference. If production telemetry shows this is material, it should be handled as a separate explicitly modeled lineage problem rather than weakening this build's ownership rules.
