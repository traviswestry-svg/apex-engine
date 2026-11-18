# APEX Stage 3B.3.2 — Historical Gamma Policy Provenance & Versioned Eligibility Contract Verification

## Build status

**Candidate built, 24 selected tests passed (12 new; 12 Stage 3B.3.1 regressions).** Not deployed, not validated against live production databases, and not full repository CI.

## Evidence reviewed

- `APEX_69_10_14_CANONICAL_GAMMA_EVIDENCE_IDENTITY_DECISION_TIME_PROVENANCE.md` from the November 12 APEX snapshot documents `canonical_gamma_snapshot_id`, `LEGACY_OR_UNKNOWN`, and the explicit restriction on replacing missing historical gamma IDs with the latest gamma snapshot.
- `config/apex_release_manifest.json` from the same snapshot reports current `apex_version=69.10.47`, `database_schema_version=8`, and `released_at=2026-10-20`. This file is **not evidence of exact historical deployment boundaries for any individual record**.
- Stage 3B.3.1 production observation: of 8 sampled decisions, 4 IDs were present and 4 null; of 8 sampled triggers, 2 IDs were present and 6 null. Presence/null alone does not decide past eligibility.

## What is implemented

A new standalone diagnostic `scripts/apex_stage3b32_historical_gamma_policy_audit.py`:

1. Bounded, SHA-256-fingerprinted source documentation and release-manifest inspection; no arbitrary source dump.
2. Identifies documented historical/legacy contracts without certifying their deployment-effective dates or upgrading null links to rule violations.
3. Optional bounded oldest/newest SQLite metadata cohort sampled with `mode=ro` and `PRAGMA query_only=ON`, without archive BLOB reads, JSON payload reads, record IDs, or timestamps in output.
4. Strict outputs: `historical_policy_effective_dates_verified=false`, `production_rule_eligibility_verified=false`, `BLOCKED_RESEARCH_ONLY`.
5. Does not change archive readers, gamma references, trader decisions, app routes, schemas or schedules.

**Important scope:** Historical eligibility cannot be independently classified from manifest metadata and source text alone. This stage produces a reproducible *evidence inventory and coverage report*, not an authoritative policy chronology or an automated enforcement engine.

## Recommended Render execution

Only after review, full CI, and deployment:

```bash
python scripts/apex_stage3b32_historical_gamma_policy_audit.py \
  --repo-root . \
  --root /data \
  --sample-rows 4 \
  --query-budget-ms 400 \
  --total-budget-ms 8000 \
  --output /tmp/apex-stage3b32-gamma-policy.json
cat /tmp/apex-stage3b32-gamma-policy.json
```

This runs a read-only sample. The SQLite progress handler is cooperative and cannot hard-limit blocking I/O. It should be operator-initiated outside market hours.

## Remaining gates

- Independent, dated deployment/change-control evidence establishing which release was active at each relevant decision/trigger creation time.
- Grounded policy contract by eligibility context; source/version provenance ties into each historical record.
- Comprehensive population-wide identity audit; actual reader/call-graph compatibility.
- Stage 3B.1 invalid UTF-8 reader fix review and verification.
- Historical engine replay equivalence; external backup restore and isolated rollback verification.

No production compression migration is authorized.
