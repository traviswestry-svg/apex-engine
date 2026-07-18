# APEX 13.0 Sprint 6 — Deployment and Rollback

## GitHub deployment

1. Back up the Render persistent disk or the file configured by `APEX_GOVERNANCE_DB`.
2. Replace the repository with the complete Sprint 6 package or apply the changed-files package.
3. Commit and push to the production branch.
4. Confirm Render uses the same persistent-disk path for `APEX_GOVERNANCE_DB`.
5. Deploy normally. Schema v5 initializes idempotently during application route registration.
6. Verify:
   - `/api/learning/status`
   - `/api/learning/readiness`
   - `/api/learning/candidates`
   - `/api/learning/audit`
   - `/apex_os/adaptive_learning`

## Database notes

Schema v5 adds new tables and indexes only. Existing candidate, outcome, history, vector, shadow, drift, and audit records are not rewritten or deleted.

## Code rollback

1. Restore the Sprint 5 application code.
2. Keep the governance database in place. Sprint 5 ignores the additive Sprint 6 tables.
3. Redeploy and verify the Sprint 5 health and research endpoints.

## Candidate rollback

Use `POST /api/learning/candidates/<candidate_id>/rollback` with an actor, reason, and optional restored version. This changes only candidate governance state and writes rollback/audit records. It does not autonomously alter production trading policy.

## Emergency safety action

Do not delete governance history. Disable access to candidate write endpoints at the proxy or application-auth layer if required, retain the database, and redeploy the prior code package.
