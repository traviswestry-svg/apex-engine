# APEX Stage 3B.3.4 — Historical Gamma Implementation Commit & Runtime Activation Provenance Audit

## Candidate scope
Research-only, operator-run script: `scripts/apex_stage3b34_gamma_commit_activation_audit.py`. It consumes the **actual** output files of Stage 3B.3.3.2: `deployment-history.json` and `render-native-evidence.json`. It does not replace previous scripts or create new archives.

## What is tested
- Correlates normalized successful deployment claims with the separately retained native Render successful `deploy_ended` event, within bounded inputs and matching service/deployment/time constraints.
- Preserves replaced/deactivated successful deployment evidence; excludes unknown/failed statuses and duplicate deployment IDs.
- Uses **read-only local Git commands** (`rev-list`, `show`) to inspect full SHA commits, first-parent markers, and the five existing gamma/evidence modules. The markers `canonical_gamma_snapshot_id` and `LEGACY_OR_UNKNOWN` are **heuristics**, not proof of actual execution. Git availability, complete history, and earlier parent coverage can be absent.
- Optionally classifies bounded runtime-observation JSON claims. No current runtime signal is implicitly trusted: every runtime claim is **unauthenticated** even if it matches commit and service.
- Does not infer a first-ever historical implementation, feature activation, effective date, or record-level eligibility from deploy success/marker presence. `BLOCKED_RESEARCH_ONLY` is unconditional.
- No DB reads, API requests, raw payload output, git mutation, backfill, reader cutover, record changes, or trading authority.

## Operator command (after integration/CI/deployment)
```bash
python scripts/apex_stage3b34_gamma_commit_activation_audit.py \
  --repo-root . \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployment-history /data/apex_audit_evidence/deployment-history.json \
  --native-evidence /data/apex_audit_evidence/render-native-evidence.json \
  --output /tmp/apex-stage3b34-gamma-provenance.json
cat /tmp/apex-stage3b34-gamma-provenance.json
```
Optional: `--runtime-attestations /data/apex_audit_evidence/runtime-gamma-observations.json` with JSON object `{"observations":[{"service_id":"srv-...","commit_sha":"<40 hex>","observed_at":"<UTC ISO timestamp>","feature":"canonical_gamma_decision_time_identity","state":"enabled|disabled"}]}`. **Do not create or backfill such claims without actual independent observation.**

## Tested
- 14 focused tests passed; 41 earlier-stage tests passed, 1 pre-existing skipped: 55 passed, 1 skipped in selected CI.
- End-to-end offline smoke with eight actual Render deployment records and sixteen lifecycle events: eight correlated successful deploys; seven previously deactivated and one currently live, **zero runtime activation verified**. In the local test workspace Git history is absent, as appropriately reported.
- Full repository CI and real production execution pending.

## Migration gates
Historical first implementation and ancestry proof; independently authenticated provider events; observable runtime feature activation; record time/version origin; historical eligibility; population-wide identity checks; historical replay; reader UTF-8 fix; reader coverage; external backup restoration and isolated rollback. **No migration authorization.**
