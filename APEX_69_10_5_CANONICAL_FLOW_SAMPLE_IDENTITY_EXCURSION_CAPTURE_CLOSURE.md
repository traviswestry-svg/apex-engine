# APEX 69.10.5 — Canonical Flow Sample Identity & Excursion Capture Closure

## Baseline
Authoritative repository audited first: **APEX 69.10.4 — Cluster Greek Structure & Multi-Horizon Transition Context**.

The live 69.10.4 production evidence showed that the upstream flow-learning repair was successful: source clusters and writer invocations were present. The remaining failure was downstream at the canonical feature/excursion boundary: thousands of source-stage observations were being counted as `missing_feature_sample` before an immutable feature sample was eligible to exist, while the feature writer itself reported no canonical capture target.

This build closes that boundary without changing trading logic, decision authority, execution authority, calibration policy, replay freshness, settlement requirements, or historical evidence.

## Root cause
`engine.flow_pl_pipeline` still contained a legacy 69.4.1 pre-writer excursion hook. The scanner called the flow P/L pipeline first and the feature writer second. Therefore the pipeline could attempt to resolve a canonical feature identity before the cluster was sealed, before replay-frame freshness was validated, and before `flow_features` persistence.

That behavior had two integrity problems:

1. Ordinary pre-persistence candidates inflated `missing_feature_sample` even though no canonical feature row should yet exist.
2. The source-stage resolver used a coarse legacy cluster key and selected the latest sealed identity, which could attribute a current cluster observation to the wrong sealed incarnation when multiple immutable samples shared the same coarse key.

The canonical architecture already declared the feature writer to be the production excursion owner. This build removes the conflicting pre-writer behavior and makes the declared authority real.

## Changes

### 1. Source-stage canonical capture is forbidden
`engine.flow_pl_pipeline` still prices live flow and records raw/cluster P/L observations, but it no longer attempts canonical sample excursion capture.

The source stage does **not**:
- reconstruct a feature `sample_id`
- resolve a coarse legacy key for capture authority
- record `missing_feature_sample` merely because the writer has not run yet
- create or update `flow_sample_excursions`

Canonical excursion capture is owned only by `engine.feature_store_writer` after exact feature persistence.

### 2. Exact post-persistence identity boundary
`engine.feature_store_writer` now centralizes canonical capture through one post-persistence helper.

Before any live excursion mark is persisted, the writer must:
1. confirm the cluster is sealed
2. resolve a decision-time replay frame within the existing freshness bound
3. build the immutable pre-decision vector
4. persist or confirm the exact `flow_features.sample_id`
5. re-read that exact feature row
6. register and verify the exact lineage mapping
7. record the real P/L mark under that same `sample_id`

A candidate rejected before step 4 is a **pre-persistence skip**, not a capture failure.

### 3. Identity registration now verifies persisted lineage
`flow_sample_identity_map` remains the authoritative lineage bridge, but `register_sample_identity()` no longer treats `INSERT OR IGNORE` as proof of success.

After the duplicate-safe insert, the persisted row is read back and all identity fields must match:
- `sample_id`
- `session_date`
- `legacy_cluster_key`
- `decision_time`

A uniqueness collision fails closed and suppresses excursion capture.

### 4. Canonical capture telemetry separated from legacy counts
The existing durable audit counters are preserved; no historical telemetry is rewritten.

New forward-only counters start at 69.10.5:
- `canonical_capture_attempts`
- `canonical_missing_feature_sample`
- `identity_registration_failures`

The old `missing_feature_sample` value is retained for compatibility and explicitly identified as potentially containing pre-69.10.5 source-stage attempts.

### 5. Scanner flow-learning observability clarified
The scanner heartbeat now separates:
- legacy `samples_recorded` semantics
- `flow_pl_observations_recorded`
- `sealed_feature_candidates`
- `skipped_before_persist_no_frame`
- `skipped_before_persist_refused`
- `canonical_lookup_missing`
- `identity_registration_failures`
- canonical capture attempts/inserts/updates/errors

New writer states include:
- `PRE_PERSIST_REPLAY_FRAME_GATED`
- `CANONICAL_FEATURE_LOOKUP_MISSING`
- `IDENTITY_REGISTRATION_FAILED`

The existing replay-frame freshness guard remains unchanged and fail-closed.

### 6. Read-only storage-capacity warning
The governed storage-retention audit now exposes an observational capacity state with default thresholds:
- `WARN` below 25% free
- `CRITICAL` below 15% free

This does **not** delete, vacuum, prune, checkpoint, or mutate anything automatically. Existing human-approval and preservation guardrails remain intact.

## Explicit non-changes
- no decision threshold changes
- no confidence/conviction changes
- no evidence-eligibility changes
- no execution authority
- no broker mutation
- no automatic calibration activation
- no synthetic P/L
- no synthetic excursion evidence
- no historical excursion backfill
- no relaxation of the 600-second replay-frame freshness bound
- no automatic storage cleanup
- no deletion of canonical decisions, grades, feature vectors, excursions, or calibration evidence

## Deployment verification
During the next live SPX session, expected evidence is:

1. `source_clusters` continues to increase.
2. `writer_invocations` continues to increase.
3. `skipped_before_persist_no_frame` may increase when replay context is legitimately unavailable; this must not increase canonical missing-feature failures.
4. `canonical_capture_attempts` increases only for exact persisted feature samples.
5. `canonical_missing_feature_sample` should remain zero under normal operation.
6. `identity_registration_failures` should remain zero.
7. `excursions_inserted` / `excursions_updated` should begin advancing when real P/L is available for persisted samples.
8. The legacy cumulative `missing_feature_sample` count may remain high because this build intentionally does not rewrite historical telemetry.

## Release
- `apex_version`: **69.10.5**
- `semantic_version`: **69.10.5**
- `application_version`: **69.10.5**
- Build: **Canonical Flow Sample Identity & Excursion Capture Closure**
