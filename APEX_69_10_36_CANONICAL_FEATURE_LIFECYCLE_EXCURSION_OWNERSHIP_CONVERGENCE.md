# APEX 69.10.36 — Canonical Feature Lifecycle & Excursion Ownership Convergence

## Rule

Persist identity once. Persist the observable origin-event repricing facts at that same canonical boundary. Re-observe only the already-bound owner. Never infer ownership from later market attributes.

## Forward path

`persisted feature sample -> exact identity registration -> immutable event binding + durable event facts -> later observational re-pricing -> exact sample excursion -> exact-ID settlement`

The event facts are not an identity resolver. `sample_id` ownership comes exclusively from `flow_feature_origin_bindings` and must validate against `flow_sample_identity_map` before an excursion write.

## Compatibility

Older bindings that predate 69.10.36 may continue to use existing `flow_pl_tracking` facts when present. The release does not backfill missing historical origin facts and does not reconstruct historical sample identities.
