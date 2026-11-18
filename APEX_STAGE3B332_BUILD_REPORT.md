# APEX Stage 3B.3.3.2 — Authenticated Render Deployment Timeline & Lifecycle Evidence Collection

**State:** ADDITIVE RESEARCH CANDIDATE. **Migration authority:** `BLOCKED_RESEARCH_ONLY`.

## Scope and actual provenance

The read-only tool `scripts/apex_stage3b332_render_evidence_collector.py` collects original Render deployment/event information into a bounded local artifact for the already-deployed Stage 3B.3.3.1 reconciliation. It does **not** modify the prior audit or any APEX trading/data modules.

Two ways to supply records:

1. `--mode api`: Performs **GET-only** requests to the official Render HTTPS API using a `RENDER_API_KEY` already supplied via the environment. The collector never writes the key. This is an authenticated API acquisition session; it is **not a cryptographically signed Render attestation**, not independent proof that a historic deployment served traffic, and not proof that the gamma feature was activated.
2. `--mode offline`: Takes raw Render provider JSON arrays (or supported list response wrappers) for deployments and events. Operator supplied JSON is **unauthenticated**; never call it authenticated solely because it resembles a Render response. This mode does not need or obtain a Render API key. If raw responses are produced by a connected app, preserve their original IDs and source context separately.

**No credentials are bundled or needed to inspect these files.** Do not paste any API keys into chat or source code. If the Render Shell has no API key, direct mode will fail closed with a clear message; use offline mode with genuine provider exports instead. Configuring a token in production is a distinct operator security decision.

## Native Render event semantics

The collector recognizes native `deploy_started` and `deploy_ended`. It only issues a Stage 3B.3.3.1-normalized successful deployment completion **claim** when `deploy_ended.details.deployStatus == 'succeeded'`, and preserves native event ID/type/deploy ID/time/status separately. It does not invent native Render `deploy_activated` event types: `deploy_activated` is the previous audit's *internal normalized label*, not the provider's original event. The output never asserts that gamma runtime activation was proven. `finishedAt` is treated as a deployment completion timestamp, not direct traffic/feature activation proof.

## Files produced

Directory defaults to `/data/apex_audit_evidence` (persistent Render disk):

- `deployment-history.json`: fields `deployments[]` and `events[]` for Stage 3B.3.3.1, up to its 2 MiB input cap. Historical `deactivated` status is preserved exactly.
- `render-native-evidence.json`: sanitized native event metadata, provenance classification, limits, completeness indicators and counts. No API token or event details body is exported.

Writes are atomic and mode `0600` for both files. SHA-256 sums printed are **integrity fingerprints**, not provenance authentication. If the collector fails during acquisition, it will not overwrite existing evidence files; remove outdated files only with deliberate operator review.

## Usage after integration/full CI

### A. Direct API mode — only if the operator already has an approved Render API key available to the process

```bash
python scripts/apex_stage3b332_render_evidence_collector.py \
  --mode api \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --max-deployments 128 --max-events 256 \
  --out-dir /data/apex_audit_evidence
```

The key must be exposed as `RENDER_API_KEY` via an approved secure mechanism. No key is configured by the candidate. The API may impose pagination and endpoint retention limits, and a bounded 128/256 sample is not necessarily the historical gamma-policy launch period.

### B. Offline mode — no token, requires real raw provider JSON saved by the operator

```bash
python scripts/apex_stage3b332_render_evidence_collector.py \
  --mode offline \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --raw-deployments /data/apex_audit_evidence/raw-render-deploys.json \
  --raw-events /data/apex_audit_evidence/raw-render-events.json \
  --out-dir /data/apex_audit_evidence
```

**Do not substitute synthetic lifecycle event records.** If the event source is incomplete or nonexistent, retain `events: []` and an explicit missing-evidence limitation.

### C. Stage 3B.3.3.1 downstream reconciliation

```bash
python scripts/apex_stage3b331_render_lifecycle_gamma_audit.py \
  --repo-root . \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployments /data/apex_audit_evidence/deployment-history.json \
  --output /tmp/apex-stage3b331-render-lifecycle.json
cat /tmp/apex-stage3b331-render-lifecycle.json
```

Even a successful result will report `event_claims_are_authenticated: false` in Stage 3B.3.3.1 because its offline processing has no cryptographic/provider-session linkage; that limitation is intentionally unchanged. The provenance report records direct API session versus offline source separately.

## Tests and limitations

- **22 new/compatibility tests passed**, including tests for exact deployment lifecycle semantics, duplicates/conflicts, invalid source IDs, failed deployment events, token absence, secure output modes and Stage 3B.3.3.1 compatibility.
- **20 existing Stage 3B.3.3.1 tests passed**. Full repository CI not run.
- No live production API call or production Render Shell execution was performed in the candidate development environment. Render's linked service tool was consulted to confirm the native event structure (`deploy_ended` with `details.deployStatus`).
- List pagination is bounded; provider retention, truncated samples or missing older events cannot establish exhaustive history. Absence of an event is not proof that a deployment never served traffic.
- Event success and source commit correspondence do not establish when the gamma policy was enabled, eligibility for any historical record, archive reader compatibility or migration authority.

**Production migration remains `BLOCKED_RESEARCH_ONLY`.**
