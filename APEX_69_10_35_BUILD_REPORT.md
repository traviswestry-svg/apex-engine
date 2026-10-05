# APEX 69.10.35 — Canonical Settlement Cohort Identity Alignment

## Release
- Version: **69.10.35**
- Build: **Canonical Settlement Cohort Identity Alignment**
- Database schema: **8 (unchanged)**
- Starting point: reconstructed canonical 69.10.34 from the Oct 4 full repository plus authoritative 69.10.30–69.10.34 changed-file releases.

## Confirmed bottleneck
Settlement enumerated unlabelled feature sample IDs and asked the exact canonical excursion reader for those IDs. Production diagnostics showed a zero exact intersection between the requested cohort and the session's excursion-bearing cohort. Existing code also retained a legacy singleton coarse-key compatibility fallback after the exact lookup. That fallback is incompatible with the new exact-owner invariant and is disabled by this release.

## Canonical invariant
A label may be written only when the exact canonical feature sample ID requested by settlement is the same ID owning the persisted excursion:

`settlement.requested_sample_id == feature.sample_id == lifecycle.sample_id == flow_sample_excursions.sample_id`

No fuzzy matching, nearest-time join, reconstructed identity, historical backfill, synthetic MFE/P&L, relaxed settlement requirement, or cross-sample excursion borrowing is introduced.

## Implementation
### Pre-write identity partition
`engine/flow_pl_store.py` adds `settlement_identity_alignment_diagnostic()`. Before any label write, settlement now partitions identity into four mutually exclusive sets:
- `REQUESTED_AND_EXCURSION`
- `REQUESTED_NO_EXCURSION`
- `EXCURSION_NOT_REQUESTED`
- `FEATURE_ONLY_UNREGISTERED`

Each sampled row includes exact-ID provenance from the identity map, lifecycle, origin-event bindings, excursion ownership, and settlement request.

### Identity-fork localization
The diagnostic reports:
- `FEATURE_TO_LIFECYCLE`
- `LIFECYCLE_TO_EXCURSION`
- `EXCURSION_TO_SETTLEMENT`
- `NONE`

This localizes where newly captured canonical identity stops progressing without inventing a replacement owner.

### Exact-owner settlement only
`engine/feature_store_writer.py` continues to read canonical excursions through `get_sample_excursions(sample_ids)`. The legacy singleton coarse-key recovery path is disabled for label creation. Missing exact excursion ownership remains pending/blocked.

### Existing 69.10.34 experiment preserved
Open Discovery prospective forward validation remains observational and unchanged. This release does not change candidate rules, thresholds, learning eligibility, decision authority, execution authority, or order submission.

## Acceptance semantics
Historical divergence is retained as diagnostic evidence and is not repaired. Production acceptance requires newly captured post-release observations to naturally progress through feature persistence -> lifecycle registration -> exact excursion ownership -> settlement request -> label under the same canonical sample ID. Historical rows are not backfilled or reconstructed.

## Release guardrails
Manifest and capability registry explicitly declare:
- exact excursion owner required;
- legacy singleton settlement recovery disabled;
- nearest-time matching disabled;
- cross-sample borrowing disabled;
- synthetic MFE/P&L disabled;
- historical identity backfill disabled;
- no learning-eligibility change;
- no trade-decision change;
- no execution-authority change.

## Validation
- Dedicated 69.10.35 tests: **3 passed**.
- APEX 69.10.x lineage: **216 passed**.
- Feature-store / flow suites excluding Flask-dependent API module: **299 passed**.
- `python -m compileall -q engine`: **passed**.
- Broad repository collection: **blocked by environment dependency** (`ModuleNotFoundError: flask`) across 67 test modules. No product-code failure was hidden or reclassified.

## Production checks after deployment
Inspect `canonical_settlement_identity_alignment` in settlement session reports. For new sessions, follow the four-set counts and `identity_fork_stages`. A new label is valid only if its sample ID was in `REQUESTED_AND_EXCURSION`; any exact-ID fork remains blocked.

## Behavioral authority
- Automatic execution: **NO**
- Automatic order submission: **NO**
- Trade decision changes: **NO**
- Learning eligibility changes: **NO**
- Historical evidence reconstruction: **NO**
