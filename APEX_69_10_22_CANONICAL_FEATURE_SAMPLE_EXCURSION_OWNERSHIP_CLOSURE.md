# APEX 69.10.22 — Canonical Feature Sample Excursion Ownership Closure

## Purpose
69.10.21 proved that the settlement-requested set is the *unlabelled* feature cohort. Therefore, `excursion_not_requested` is not itself evidence of a broken writer: samples with valid excursions may already have labels and no longer appear in the pending set.

69.10.22 closes the actual integrity boundary. Canonical excursion writes now require the exact persisted feature-sample owner tuple `(sample_id, session_date, legacy_cluster_key, decision_time)` before a write is accepted.

## New observability
Settlement publishes `canonical_pending_outcome_eligibility` per session and `canonical_pending_outcome_summary` across the settlement run. Pending samples are separated into:
- `awaiting_real_pl`
- `pl_observed_without_excursion`
- `excursion_state_without_excursion`
- `no_lifecycle_record`
- `feature_only_unregistered`
- `exact_excursion_present`
- `ownership_integrity_failures`

The audit is read-only and does not create P/L, excursions, labels, identities, or execution authority.

## Guardrails
- exact registered owner required for canonical writes
- no reconstructed identity
- no fuzzy/nearest-time matching
- no synthetic P/L or excursions
- no historical backfill
- no settlement-label fabrication
- no decision/execution authority changes

## Production acceptance
For new forward data, canonical writes must continue to show zero ownership refusals under normal operation and exact readback verification. Pending settlement samples should predominantly classify as `AWAITING_GENUINE_REAL_PL`; any `PL_OBSERVED_WITHOUT_EXCURSION`, `EXCURSION_STATE_WITHOUT_ROW`, or owner-tuple mismatch is a true integrity defect requiring follow-up.
