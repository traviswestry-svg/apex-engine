# APEX Stage 3B.3.3.1 — Historical Render Deployment Lifecycle & Gamma Activation Evidence Reconciliation

**Status:** CANDIDATE_READ_ONLY_RESEARCH · **Migration:** `BLOCKED_RESEARCH_ONLY`

## Scope

The earlier Stage 3B.3.3 audit rejected every historical deployment with current Render status `deactivated`. The new `scripts/apex_stage3b331_render_lifecycle_gamma_audit.py` is an additive diagnostic; it does not replace or modify `scripts/apex_stage3b33_deployment_gamma_contract_audit.py`.

The new audit distinguishes current `live` deployments from historical `deactivated` deployments. A deactivated deployment is **not** assumed to have been activated. An explicitly deployment-linked and successful **normalized activation event claim** can elevate it to a *candidate historical activation* for local Git policy inspection. No claim in an offline file is authenticated merely by matching IDs or timestamps. Failure, unknown status, unlinked events, events before start or after a supplied deactivation time, conflicting markers, duplicate IDs, and missing Git evidence are not promoted to effective-date proof.

## Inputs and provenance boundary

- `--deployments` accepts up to 128 deployments and 256 lifecycle events (configurable within bounds), read locally only, 2 MiB maximum file.
- `deployments[]`: `deploy_id`, `service_id`, full 40-character `commit_sha`, `status`, timezone-aware `started_at`, timezone-aware `live_at`; optional `deactivated_at`. The `live_at` value is a claimed completed/live timestamp from the source; it **does not independently attest live traffic or activation**.
- `events[]`: `deploy_id`, `service_id`, `event_type` (`deploy_activated` or `deploy_live`), `outcome` (`succeeded`), timezone-aware `occurred_at`.
- **Event types in this example are normalized *claims*, not guaranteed Render native event names.** A Render `deploy_ended` event is not automatically a successful activation; do not rename raw events into success without documented source-status evidence. Preserve the raw provider event alongside the normalized claim in the operator's separately retained original export.
- Export files remain `EXPORT_PROVIDED_NOT_AUTHENTICATED`, including manually transcribed records. The script has no network calls, no API key use and no remote provenance verification.
- Local Git verification uses the prerequisite Stage 3B.3.3 `git_validate()` contract check; a matching code marker does **not** prove feature activation.

## Execute (after integration and full CI)

```bash
python scripts/apex_stage3b331_render_lifecycle_gamma_audit.py \
  --repo-root . \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --deployments /tmp/apex-deployment-history.json \
  --output /tmp/apex-stage3b331-render-lifecycle.json
cat /tmp/apex-stage3b331-render-lifecycle.json
```

The previous three-record file lacks `deploy_id`; it will produce `MISSING_OR_INVALID_DEPLOY_ID` until regenerated from the original Render records. This is expected and must not be fixed by inventing IDs. A lifecycle-event export can be omitted (`events` defaults to empty), in which case historical deactivated deployments remain unverified.

## Validation

20 focused local tests passed; 16 Stage 3B.3.3 baseline tests passed. Full repository CI, historical production export acquisition, external authenticity verification and production execution **not** performed. The test suite includes a copy of the unchanged predecessor solely as a fixture dependency; do not deploy `_stage3b33_test_dependency.py` as a production module.

## Remaining authority gates

Historical deployment/event authenticity; commit implementation; actual runtime feature activation; record-to-deployment provenance; cross-database population checks; Stage 3B.1 UTF-8 reader correction; full engine replay; reader cutover coverage; external backup restoration; isolated rollback. None are automatically satisfied.
