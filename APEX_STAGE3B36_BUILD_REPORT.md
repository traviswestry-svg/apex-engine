# APEX Stage 3B.3.6 — Historical Gamma Implementation Origin & Deployment Boundary Discovery

**Delivery:** Additive, candidate-only, read-only research audit. **Migration authority:** `BLOCKED_RESEARCH_ONLY`.

## Purpose

Stage 3B.3.5 found gamma-policy marker strings in the parents of all eight sampled deployment commits. Stage 3B.3.6 searches **earlier history** of the existing external Git mirror for marker occurrence-count changes, checks source snapshots at those changed commits and their *direct parents*, and evaluates Git ancestry relative to lifecycle-corroborated Render deployment revisions.

An introduced string is a **marker introduction candidate only**, not proof of code semantics, implementation completeness, active runtime features, historical first implementation, or a verified policy-effective timestamp.

## Files

- `scripts/apex_stage3b36_gamma_origin_discovery.py` — new CLI, read-only.
- `scripts/apex_stage3b35_git_boundary_audit.py` — existing 3B.3.5 dependency, included unchanged for reproducible integration; **do not overwrite a different deployed version without comparing**.
- `tests/test_apex_stage3b36_gamma_origin_discovery.py` — 10 focused tests.
- `tests/test_apex_stage3b35_git_boundary_audit.py` — 14 regression tests, unchanged.
- `INTEGRATION_MANIFEST.json` — manifest.

## Method and limits

1. Reuses 3B.3.5's strict deployment/native-event/normalized-event matching.
2. Inspects the existing Git checkout/mirror; **never** fetches, clones, modifies refs, imports application modules, or opens databases.
3. Uses `git log --all -S<marker> -- <five source modules>` for two known gamma-provenance strings: `canonical_gamma_snapshot_id` and `LEGACY_OR_UNKNOWN`. The search is bounded to 128 changed commits by default (hard maximum 256) and at most 25 seconds per search; more than the budget fails closed. `-S` does not find every semantic change or all renames / migration paths.
4. Compares changed commits and their immediate parents. Full presence of *both marker strings* in source modules together with absence in all parents constitutes a **source-marker boundary candidate** only. If a parent contains markers, it is not a direct-parent candidate. Incomplete source paths are flagged as incomplete coverage.
5. Relates candidates to successful sampled Render deployments via Git `merge-base --is-ancestor`. No inference of effective dates, production activation, or record eligibility.
6. Default report contains aggregate counters and no Git SHA or deployment IDs. `--private-details-output` optionally saves candidate commit IDs and ancestry counts to a separate mode-0600 local JSON file; do not publish it or treat it as attestation.
7. Any missing Git history, failed marker search, or exceeded search cap suppresses candidate findings rather than returning a misleading partial origin set.

## Test results

- `python -m pytest -q tests/test_apex_stage3b36_gamma_origin_discovery.py tests/test_apex_stage3b35_git_boundary_audit.py` -> **24 passed**, 0 failed.
- Includes a genuine bare Git clone fixture; before/after source marker checks; lifecycle failure; search cap; missing mirror; no SHA leaks in aggregate report; mode 0600 candidate evidence.
- Offline integration with actual previously collected **8 Render deployments / 16 native events**: 8 lifecycle-corroborated, no Git results when using a deliberately absent mirror, `BLOCKED_RESEARCH_ONLY`. This does not constitute a production run with the user's historical Git mirror.
- Full repository CI, production runtime, historic semantic behavior, provider-signed deploy authentication, and historical gamma activation are **not** verified.

## Render command (after code review, CI, and deployment)

```bash
python scripts/apex_stage3b36_gamma_origin_discovery.py \
  --git-repository /data/apex_audit_evidence/apex-git-mirror \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployment-history /data/apex_audit_evidence/deployment-history.json \
  --native-evidence /data/apex_audit_evidence/render-native-evidence.json \
  --output /tmp/apex-stage3b36-origin-report.json \
  --private-details-output /data/apex_audit_evidence/stage3b36-private-candidates.json

cat /tmp/apex-stage3b36-origin-report.json
```

The optional private artifact retains candidate SHAs; the summary intentionally omits them. The present eight deployment records are too recent to validate the original policy deployment boundary. Acquire older Render deployment/event records through a documented provider source **separately**, after establishing code-side candidates.

## Remaining gates

Independently authenticated full Git provenance, behavior-level source review, older provider-attested deployment lifecycle, runtime activation attestation, historical record origin mapping, gamma population identity, stage3b1 UTF-8 reader fix, replay equivalence, reader cutover coverage, external backup restore, and isolated rollback. No migrations or production trading permissions are granted.
