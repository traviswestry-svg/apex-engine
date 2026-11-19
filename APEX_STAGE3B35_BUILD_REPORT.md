# APEX Stage 3B.3.5 — Verified Historical Git Commit Provenance & Gamma Implementation Boundary Audit

## Build scope

New independent diagnostic: `scripts/apex_stage3b35_git_boundary_audit.py`.

**No production migration authority.** The audit consumes the existing Stage 3B.3.3.2 `deployment-history.json` and `render-native-evidence.json` without modifying them or the production databases. It performs only read-only, local Git object queries against an **operator-supplied separate Git checkout/mirror**. No GitHub API calls, network operations, `git fetch`, `git clone`, checkout, reset, or Git mutations are performed.

## Verification model

1. Require full-length SHA-1 format deployment commit IDs, valid deployment IDs, timezone-aware timestamps and allowed deployed/replaced lifecycle statuses.
2. Correlate a normalized Stage 3B.3.3.2 success claim with a native `deploy_ended` succeeded event for the same deployment, service and near-identical completion time.
3. Inspect the corresponding Git commit object, five historical evidence/gamma modules, and **all immediate parents**. Read-only Git commands use a 3-second timeout and bounded output; automatic lazy-fetch is disabled.
4. Report a **direct-parent marker introduction candidate** only if all required source files are present at the commit, both heuristic markers are found, all parent objects and files are available, and neither parent shows the complete marker set.
5. Report missing, shallow, incomplete, or inaccessible history as unverified. The marker check cannot prove functional correctness, feature gating, original historical introduction, or exact policy activation.
6. Suppress individual commit IDs, deployment IDs, source payloads and policy-effective timestamps from the aggregate report.

## Limitations

- Git markers `canonical_gamma_snapshot_id` and `LEGACY_OR_UNKNOWN` are heuristics; a candidate change is **not** independently verified gamma-policy semantics or the first-ever implementation.
- The audit does **not** authenticate the externally supplied Git checkout/mirror or the offline provider export. Operators must verify the origin and complete history separately.
- Merges, rewritten histories, omitted files, alternate feature flags, shallow repositories, and absent parent objects prevent conclusive classification.
- There is no runtime activation attestation, per-record version origin, historical gamma eligibility determination, or retrospective effective date authorization.
- No database reads, compression changes, archive mutations, new reader selection, background work, or trade execution.

## Operator command

Supply a verified historical Git checkout or bare mirror that already exists on an approved path. **Do not point `--git-repository` at the production source directory unless it actually contains the required Git history.**

```bash
python scripts/apex_stage3b35_git_boundary_audit.py \
  --git-repository /data/apex_audit_evidence/apex-git-mirror \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployment-history /data/apex_audit_evidence/deployment-history.json \
  --native-evidence /data/apex_audit_evidence/render-native-evidence.json \
  --output /tmp/apex-stage3b35-git-boundary.json
cat /tmp/apex-stage3b35-git-boundary.json
```

The mirror path is an example, **not** an assertion that a mirror exists there. If the mirror is absent, the script produces a safe `GIT_REPOSITORY_UNAVAILABLE` report. Acquire an authenticated, complete Git repository separately using your organization's approved workflow; do not install Git credentials or remote fetches into the running APEX service solely for this audit.

## Validation

- **14/14** focused tests passed, using an actual two-commit Git fixture for direct-parent marker introduction.
- **71/71** prior-stage regression tests passed (Stages 3B.3.3, 3B.3.3.1, 3B.3.3.2, and 3B.3.4); **one prior test skipped**.
- **85 passed, 1 skipped** in the combined selected suite. Full repository CI not performed.
- Offline integration with existing 8-deployment / 16-event provider extract: **8/8 lifecycle correlations**; absent Git mirror properly classified `GIT_REPOSITORY_UNAVAILABLE`, **zero policy-effective dates assigned**.

## Remaining gates

Independent complete historical Git provenance and implementation semantics; authenticated provider deployment events; runtime gamma activation; record-version origin; population identity coverage; Stage 3B.1 UTF-8 fix; full historical replay and reader-cutover coverage; external backup and isolated rollback. Always `BLOCKED_RESEARCH_ONLY`.
