# APEX 69.10.24 — Persisted Feature Origin Identity Propagation Closure

## Objective
APEX 69.10.24 closes the forward-only provenance gap between a successfully persisted canonical flow feature sample and later genuine P/L observations produced from the same originating market objects.

The release does not infer ownership from ticker, expiration, direction, timestamps, nearest samples, reconstructed IDs, or mutable cluster state. Missing provenance remains missing and canonical evidence writes fail closed.

## Implemented provenance rule
1. `feature_store_writer.write_samples()` persists the immutable feature sample.
2. `_capture_exact_persisted_sample()` re-reads that exact `sample_id` from the feature store.
3. `flow_pl_store.register_sample_identity(..., origin_event_ids=...)` atomically verifies/registers the canonical identity tuple and publishes immutable bindings from each originating `event_id` to the exact persisted tuple.
4. On later scanner cycles, `flow_pl_pipeline.run_flow_pl()` rebuilds clusters from current tape data. It does **not** determine ownership from the rebuilt cluster's current attributes.
5. `resolve_feature_origin_provenance(event_ids=...)` succeeds only when every continuing event has an exact binding and all bindings resolve to one identical original tuple.
6. The propagated origin tuple is revalidated with `verify_sample_identity_owner()`.
7. Genuine P/L may then widen/create the excursion under the **original** sample ID and original identity tuple.
8. The existing 69.10.20 write/readback proof and exact settlement reader remain unchanged.
9. The 69.10.23 current-tuple resolver remains only as fallback observability; it never receives canonical write authority.

## Direction evolution
A sample persisted as `...|UNCERTAIN` may later be observed as `...|BULLISH` or `...|BEARISH`. The later observation may retain its current directional interpretation for diagnostics, but the evidence owner remains the original persisted sample when immutable origin provenance validates.

## New persistence
Two forward-only tables are added:

- `flow_feature_origin_bindings`: exact originating event ID → immutable canonical feature identity tuple.
- `flow_feature_origin_pl_audit`: provenance presence, validation, direction evolution, and origin-owned excursion telemetry for later P/L observations.

No historical provenance is synthesized or backfilled.

## Guardrails
- Exact registered owner required.
- Genuine P/L required.
- No fuzzy matching.
- No reconstructed identity.
- No latest-owner substitution.
- No synthetic P/L or excursions.
- No historical backfill.
- No change to trading decisions or execution authority.
- Human promotion and existing governance remain unchanged.

## Read-only diagnostics
`feature_origin_provenance_health()` exposes provenance presence/missing, validation success/failure, direction evolution, origin-owned excursion writes/updates, legacy exact-resolution diagnostics, and provenance resolution percentage.

`feature_origin_session_audit(session_date)` adds per-session persisted samples, registered identities, origin-owned excursions, awaiting-real-P/L population, labels created, and explicit non-authority flags.
