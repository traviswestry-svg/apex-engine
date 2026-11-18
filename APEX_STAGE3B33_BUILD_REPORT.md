# APEX Stage 3B.3.3 — Build and Integration Report

**Status:** Candidate implementation; offline tests passed; no production execution or migration authority.

## Grounded source evidence

Inspected the 2026-11-12 APEX source ZIP containing `APEX_69_10_14_CANONICAL_GAMMA_EVIDENCE_IDENTITY_DECISION_TIME_PROVENANCE.md`, its build report, changed-files manifest, current release manifest and the related implementation files. Four documentation markers were present: canonical snapshot identity, `LEGACY_OR_UNKNOWN`, no latest-snapshot backfill and no retroactive reclassification. Local source ZIP is **not** a deployment attestation or Git history.

## New code

`scripts/apex_stage3b33_deployment_gamma_contract_audit.py` is an offline read-only scanner. Its optional `--deployments` input expects a JSON object with a `deployments` list. Each entry has:

- `service_id`: exact Render service ID;
- `commit_sha`: **full 40-hex-character Git commit SHA**;
- `status`: exactly `live` for a candidate successful deployment;
- `started_at`, `live_at`: timezone-aware ISO-8601 timestamps.

`DEPLOYMENT_EXPORT_EXAMPLE.json` is an **illustrative placeholder only**, not real deployment evidence. Replace it with a verified export from the relevant service if available. Never label a user-created JSON file as verified Render evidence.

When a `.git` directory is present, the audit uses read-only `git show <sha>:<path>` calls to inspect source objects from reported commits. If Git history is absent or objects are unavailable, this is reported explicitly. Even a Git-confirmed policy implementation and a supplied live deployment timeline **do not** establish independently authenticated deployment, runtime feature activation or exact record-time policy eligibility. A representative historical policy-effective date is therefore **never automatically certified**.

## Production command

First integrate the candidate, run full repository CI and deploy it. The audit is offline and can run on Render without needing to open production SQLite:

```bash
python scripts/apex_stage3b33_deployment_gamma_contract_audit.py \
  --repo-root . \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --output /tmp/apex-stage3b33-deployment-policy.json
cat /tmp/apex-stage3b33-deployment-policy.json
```

If an authentic deployment-history export has been obtained and reviewed, add `--deployments /tmp/apex-deployment-history.json`. Do **not** pass the included example file as evidence. Maximum 128 entries by default; maximum 256 configurable.

The report aggregates classifications and deliberately omits deployment IDs, commit SHAs and exact timestamps. It does include SHA-256 fingerprints of **source files only**. No production DB, payload, record ID or trade decision is touched.

## Validated

- 16/16 new focused tests passed.
- Source snapshot dry-run successfully detected all four documented gamma-contract markers.
- Prior stage audit files are not replaced or modified.
- Full repo CI, production deployment reconciliation, Render export authentication and runtime activation checks are **not performed**.

## Remaining gates

Authenticated Render deployment history, commit and deployed runtime policy equivalence, feature activation, record-origin mapping, population-wide identity, historical replay, reader UTF-8 fix, archive reader cutover coverage, external backup restore and isolated rollback remain blocked.

**Migration authority: `BLOCKED_RESEARCH_ONLY`.**
