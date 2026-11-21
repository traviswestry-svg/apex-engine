# APEX Stage 3B.3.9 — Historical Gamma Runtime Activation & Decision-Time Evidence Correlation

## Build result

**Read-only candidate, not deployed or production-tested.** Built against the extracted Stage 3B.3.8 and Stage 3B.3.1 candidate sources available in this task. 86 selected tests passed, one existing test skipped. This is not full repository CI.

## New files

- `scripts/apex_stage3b39_runtime_decision_gamma_audit.py` — read-only, bounded SQLite correlation; does not import production engine modules.
- `tests/test_apex_stage3b39_runtime_decision_gamma_audit.py` — synthetic fixtures, classification, missing schema, index, boundary, and CLI regression.
- `INTEGRATION_MANIFEST.json` — additive installation instructions.

## Evidence model

- The candidate Stage 3B.3.8 boundary is `2026-09-18T13:45:00.256463Z` (Sep 18 09:45:00 EDT). Historical post-deployment `dep-damjvajncjis73dmepo0`, commit `e14c343dcd14b9987a92a45dda44bbbdf54a60e4`. The tool validates matching deployment ID, service ID, commit SHA, successful normalized claim and native completion event from the saved offline Stage 3B.3.8 export.
- This **does not** certify deployment record origin or actual gamma runtime activation; offline evidence is not provider-signed.
- Two SQLite databases, opened read-only: `/data/apex_evidence_pipeline.db` and `/data/apex_tracking.db`. Decisions are sampled from bounded oldest/newest rowid edges, and optionally near the boundary if SQLite EXPLAIN proves an indexed `observed_at` lookup. No population coverage claim.
- The decision's persisted `canonical_gamma_snapshot_id` is the **only** identity used for indexed lookup of `gamma_observational_snapshots`; no lookup of the latest gamma snapshot and no extraction of a missing ID from arbitrary payloads for backfill.
- The audit checks persisted snapshot root/nested identity conflicts, ticker agreement and gamma observation timestamp <= decision timestamp only when a trustworthy-looking source timestamp column exists. It does not independently prove gamma's availability at the historical decision time or observed producer version.
- If the gamma schema lacks a verifiable observation-time column or identifier index, the result is explicitly non-verifying. Missing ID is `POST_BOUNDARY_ID_NULL_LEGACY_OR_UNKNOWN`, not an error or authorization to fill one.
- Reports aggregate states, no record IDs/payloads or gamma IDs; mode=ro, query_only, cooperative query deadline. `migration_authority=BLOCKED_RESEARCH_ONLY` is invariant.

## Installation

Review and copy only the new script and tests into the repository. Existing Stage 3B.3.8 normalized export files need to remain on the persistent disk. Do not install by replacing any existing scripts, and do not run the tool without review/CI.

```bash
python scripts/apex_stage3b39_runtime_decision_gamma_audit.py \
  --root /data \
  --deployment-history /data/apex_audit_evidence/stage3b38-deployment-history.json \
  --native-evidence /data/apex_audit_evidence/stage3b38-render-native-evidence.json \
  --boundary 2026-09-18T13:45:00.256463Z \
  --sample-rows 8 \
  --query-budget-ms 300 \
  --total-budget-ms 10000 \
  --output /tmp/apex-stage3b39-runtime-correlation.json
cat /tmp/apex-stage3b39-runtime-correlation.json
```

Results must be interpreted conservatively. This cannot establish first runtime activation, historical record origin, semantic replay, record eligibility, production archive cutover, backup restoration, or rollback. Do not use it to justify compression migration.
