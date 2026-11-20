# APEX Stage 3B.3.8 — Historical Render Deployment Recovery & Gamma Runtime Activation Evidence Audit

## Candidate status

**ADDITIVE / READ-ONLY CANDIDATE, NOT DEPLOYED IN PRODUCTION.** `migration_authority=BLOCKED_RESEARCH_ONLY` in every outcome. This is not a provider-authenticated deployment certificate or historical gamma activation attestation.

## Scope

Historical gamma source-code implementation candidate: `6f15e854b21b6406a570c100d955ccbbb0debe59` (APEX 69.10.14; Git commit September 18, 2026). Existing Stage 3B.3.7 confirmed a static source-contract candidate across five files; eight November deployments were all after the candidate. Stage 3B.3.8 specifically looks for historical deployment records before and after the candidate, and separately classifies runtime *claims*.

### Implementation

- New `scripts/apex_stage3b38_historical_render_runtime_audit.py` reuses Stage 3B.3.3.2 Render native/normalized evidence model and Stage 3B.3.7 Git/static source checks.
- **Offline mode:** ingest historical raw provider deployments/events as JSON arrays, JSON pages, or `{"pages": [ ... ]}` exports. They are never assigned a provider-authenticated status.
- **API mode:** bounded HTTPS GET to Render REST for deployments and service events using an operator-provided `RENDER_API_KEY` environment variable. Key is not printed or written; no remote mutations. **API pagination has only been tested with simulated page responses, not live against the Render API.** Pagination completeness is only asserted for an observed short/empty page; a full page without cursor is incomplete.
- Filter deployments by a bounded UTC completion-time window (default September 1–October 15, 2026), and include the corresponding native lifecycle events. Selection fails closed above 128 deployment records or 1,024 related events; narrow the window if necessary.
- Normalize with Stage 3B.3.3.2; reconcile with Stage 3B.3.7; check candidate/parent source contract and Git ancestor/descendant relationships. A before/after pair is **only an unauthenticated offline deployment bracket candidate**.
- Optional runtime claims JSON `{"observations":[{"deploy_id":"...","commit_sha":"...","observed_at":"...Z","canonical_gamma_snapshot_id":"..."}]}`. Links claims by deployment/commit/timestamp, but does **not** certify provider provenance, decision-time record integrity, or feature activation.
- Public report contains no deployment/commit IDs. Optional private report includes inherited Stage 3B.3.7 candidate bracket details; both outputs use atomic writes and `0600` permissions.
- Optional evidence output creates `stage3b38-deployment-history.json` and `stage3b38-render-native-evidence.json`, not overwriting Stage 3B.3.3.2's `deployment-history.json` / `render-native-evidence.json`.
- Explicitly guards against writing output files into the Git repository or overwriting raw inputs.
- No production database reads, historical code execution/import, Git fetch/clone/mutation, record backfill, trading, reader cutover, or migration.

## Test results

`python -m pytest tests -q` → **64 passed, 1 skipped** (selected bundled suite; repository-wide CI not run). New tests: 11 passing. Mock REST pagination, offline multi-page exports, filtering, cap failure, runtime mismatch, a synthetic Git parent→candidate and successful Render before→after bracket, no-Git fail closed, and evidence persistence.

Local end-to-end run against existing 8-deployment/16-event November raw bundle with a November window: 8 normalized deployments, 16 native events, 8 successful event claims; 0 bracket because the integration runner deliberately lacked the production Git mirror. The run made no claim about September history or activation.

## Install

Merge the candidate `scripts` and `tests` into the application repository; run CI; deploy through the normal review path. Do not copy or execute the candidate on a production runtime without approval and review. Preserve existing source files unless intentionally updating an earlier-stage copy.

### Production shell — offline historical provider exports

Supply genuine historical Render raw deploys and events in private persistent `/data/apex_audit_evidence`, collected through your authorized Render account. The old 8-deployment November files will **not** establish the September boundary.

```bash
python scripts/apex_stage3b38_historical_render_runtime_audit.py \
  --mode offline \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --git-repository /data/apex_audit_evidence/apex-git-mirror \
  --candidate-sha 6f15e854b21b6406a570c100d955ccbbb0debe59 \
  --raw-deployments /data/apex_audit_evidence/raw-render-deploys-historical.json \
  --raw-events /data/apex_audit_evidence/raw-render-events-historical.json \
  --window-start 2026-09-01T00:00:00Z \
  --window-end 2026-10-15T00:00:00Z \
  --evidence-out-dir /data/apex_audit_evidence \
  --output /tmp/apex-stage3b38-report.json \
  --private-details-output /data/apex_audit_evidence/stage3b38-private-details.json
cat /tmp/apex-stage3b38-report.json
```

### Production shell — direct HTTPS GET (optional)

Requires `RENDER_API_KEY` securely configured in the running shell environment. If unavailable, use offline mode. Do not paste API secrets in messages or shell command history. Live Render API response/pagination shape must be validated in your own environment.

```bash
python scripts/apex_stage3b38_historical_render_runtime_audit.py \
  --mode api \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --git-repository /data/apex_audit_evidence/apex-git-mirror \
  --candidate-sha 6f15e854b21b6406a570c100d955ccbbb0debe59 \
  --window-start 2026-09-01T00:00:00Z \
  --window-end 2026-10-15T00:00:00Z \
  --max-pages 48 --max-records 5000 \
  --evidence-out-dir /data/apex_audit_evidence \
  --output /tmp/apex-stage3b38-report.json \
  --private-details-output /data/apex_audit_evidence/stage3b38-private-details.json
```

### Optional runtime observation claims

Add `--runtime-observations /data/apex_audit_evidence/gamma-runtime-observations.json` only if you actually have contemporaneous, non-secret, provider- or application-sourced observations. Never fabricate examples as evidence. Even matching claims return `runtime_activation_verified=false` until an independent attestation process exists.

## Interpretation and remaining gates

Even if a historical before/after pair is found, it remains `OFFLINE_BRACKET_CANDIDATE_RUNTIME_UNVERIFIED`, not a policy-effective date or runtime proof. Need independent Git source authentication, provider-attested historical lifecycle, isolated historical behavioral tests, independent runtime gamma activation evidence, record origin/version and population identity, UTF-8 reader fix, replay equivalence, external backup/restore and rollback before any migration authority can change.
