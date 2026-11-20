# APEX Stage 3B.3.7 — Gamma Origin Candidate Semantic Verification & Historical Deployment Bracketing

**Artifact:** read-only candidate, **not** production deployment or release approval.  
**Migration authority:** `BLOCKED_RESEARCH_ONLY`.  
**Historical candidate:** `6f15e854b21b6406a570c100d955ccbbb0debe59` (APEX 69.10.14, September 18, 2026; candidate commit date is **not** runtime effective date).

## What this build does

- Inspects source **without importing or executing historical engine code** at candidate and immediate parent using bounded `git show` and Python AST parsing.
- Checks function names and contract indicators across `evidence_eligibility.py`, `historical_evidence_lifecycle.py`, `evidence_pipeline.py`, `gamma_transition.py`, and `trigger_observatory.py`.
- Distinguishes presence of a static source contract from proven correctness. Missing/incomplete source is not counted as verified semantic behavior.
- Correlates normalized Stage 3B.3.3.2 successful deployment claims with corresponding native Render `deploy_ended` successful events; rejects duplicate IDs and invalid timestamps/SHAs.
- Uses Git ancestry **in both directions** to classify deployed revisions as candidate descendants, candidate ancestors, or unclassifiable (e.g. parallel branches). Requires a chronological ancestor-before/descendant-after pair before reporting an **offline bracketing candidate**.
- Writes a public JSON summary containing no deployment IDs or commit SHAs and an optional 0600 private detail file retaining IDs/SHAs for local investigation.
- Never asserts runtime activation, provider-signed deployment attestation, eligibility, first semantic implementation, or effective date.

## Tests and integration

`python -m pytest -q tests/test_apex_stage3b37_semantic_deployment_bracketing.py tests/test_apex_stage3b36_gamma_origin_discovery.py tests/test_apex_stage3b35_git_boundary_audit.py`

**32 passed**, 0 failed. Covers direct-parent candidate, before/after deployment bracket, only-after histories, invalid native event, incomplete source contract, missing Git, duplicate IDs, SHA exclusion from public report, and file permissions.

End-to-end local check with archived Render evidence JSON: **8/8 deployment lifecycle matches**; without local Git mirror source classification intentionally `SOURCE_PROVENANCE_UNVERIFIED`. Historical September timeline **not yet supplied** to test the intended before/after bracket. Full APEX CI not run.

## Deployment / usage (after code review and CI)

Install the three additive scripts from the ZIP in `scripts/`, preserving existing scripts where versions already match.

```bash
python scripts/apex_stage3b37_semantic_deployment_bracketing.py \
  --git-repository /data/apex_audit_evidence/apex-git-mirror \
  --candidate-sha 6f15e854b21b6406a570c100d955ccbbb0debe59 \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployment-history /data/apex_audit_evidence/deployment-history.json \
  --native-evidence /data/apex_audit_evidence/render-native-evidence.json \
  --output /tmp/apex-stage3b37-report.json \
  --private-details-output /data/apex_audit_evidence/stage3b37-private-details.json
cat /tmp/apex-stage3b37-report.json
```

**Important:** Existing eight November 17–18 deployments all descended from the candidate, so they cannot bracket September 18. To test an actual before/after boundary, collect genuine earlier Render deployment/event records around September 18 into **new** inputs using the Stage 3B.3.3.2 collector. Never overwrite a known-good evidence file without retaining its copy. Offline data is still not signed or independently attested. Do not extrapolate from first observed deployment to first actual deployment.

## Explicit remaining gates

1. Isolated historical behavior testing / replay on a separate disposable environment, using representative decision-time gamma records (including missing, stale, aging, reconstructed, mismatched IDs) and precise postconditions.
2. Authenticated historical Render timeline bracketing candidate and older parent production deployment.
3. Independent runtime feature activation and record-time version provenance.
4. Source history authenticity/coverage, population identity, Stage 3B.1 UTF-8 fix, replay equivalence, external backup/restore and rollback.

No SQLite access or writes; no code import; no Git mutations or network calls; no policy reclassification, trade authority, migration, or reader cutover.
