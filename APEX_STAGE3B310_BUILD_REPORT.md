# APEX Stage 3B.3.10 — Historical Record-Origin Attestation & Gamma Population Coverage Audit

**Build status:** Additive, read-only candidate. **Migration authority:** `BLOCKED_RESEARCH_ONLY`.

## Scope

The new script `scripts/apex_stage3b310_origin_population_audit.py` reads the existing `/data/apex_evidence_pipeline.db` decision table and `/data/apex_tracking.db` gamma observational snapshots. It uses SQLite `mode=ro`, `PRAGMA query_only=ON`, read-only transactions, a bounded `rowid` keyset walk, per-query progress deadlines, global time budget, bounded row counts and parameterized indexed gamma identity lookups. It reuses the Stage 3B.3.9 read-only deployment/event correlation function. The candidate does not execute historical APEX code, read entire payload histories, or update databases, releases, policy decisions, or trade execution.

It classifies post-reference decisions as missing canonical ID, gamma ID unresolved, duplicate gamma source identity, timestamp conflict, ticker conflict, malformed/incomplete snapshot, or ID/symbol/time consistent. Historical pre-reference records retain `PRE_REFERENCE_NO_RETROACTIVE_POLICY`. It counts persisted origin/version metadata as **untrusted claims**; no provider attestation or runtime activation is inferred.

## Coverage honesty

`population_coverage_verified=true` **only** if the rowid scan exhausted the decision table, the number scanned reconciles to `COUNT(*)` in the read-only decision transaction, and no query errors occurred. Even then this means **only the locally visible `decisions` table**, not all historical writers, cross-database atomicity, a cryptographic historical population, or authenticated record origin. If max rows, query deadlines, missing source identity index or schema block completeness, the audit fails closed. The default max is 10,000 rows; selectable up to 200,000 with an explicit bounded 120-second maximum. Users should start small and increase cautiously only when resource headroom is verified.

No identifier, decision payload, individual ticker, or commit SHA is emitted to public JSON. Report path must be outside the production data root. Audit does not write under `/data` and does not assert a policy-effective deployment time.

## Selected tests executed

`PYTHONPATH=scripts pytest -q tests/test_apex_stage3b310_origin_population_audit.py tests/test_apex_stage3b39_runtime_decision_gamma_audit.py`

**19 passed** (9 new, 10 Stage 3B.3.9 regressions), zero failed. These tests use synthetic databases, not the actual production SQLite files. Full repository CI and production execution not performed.

## Production command

After integrating **only the new Stage 3B.3.10 script** and running repository CI:

```bash
python scripts/apex_stage3b310_origin_population_audit.py \
  --root /data \
  --deployment-history /data/apex_audit_evidence/stage3b38-deployment-history.json \
  --native-evidence /data/apex_audit_evidence/stage3b38-render-native-evidence.json \
  --boundary 2026-09-18T13:45:00.256463Z \
  --max-rows 10000 \
  --batch-size 200 \
  --query-budget-ms 500 \
  --total-budget-ms 20000 \
  --output /tmp/apex-stage3b310-population.json
cat /tmp/apex-stage3b310-population.json
```

## Required existing dependency

`scripts/apex_stage3b39_runtime_decision_gamma_audit.py`, already deployed in the current user's APEX environment. The new candidate imports its safe SQLite and deployment-correlator helpers; it does not change that module. If those helpers have changed in production, rerun tests on the integrated commit.

## Explicitly unverified

- Independent record-origin version attestation and runtime feature activation
- A historical policy-effective date, provider snapshot availability, and cross-DB point-in-time consistency
- Historical gamma eligibility; full semantic and replay equivalence
- Archive reader UTF-8 fix, reader cutover, external backup restore, and isolated rollback

**Do not migrate, compress/replace SQLite data, backfill gamma identities, or authorize trading because of this report.**
