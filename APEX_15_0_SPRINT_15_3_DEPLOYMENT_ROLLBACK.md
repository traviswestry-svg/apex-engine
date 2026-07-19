# APEX 15.0 Sprint 15.3 Deployment and Rollback

## Deploy
1. Back up the production database.
2. Deploy the complete repository through the existing GitHub-to-Render workflow.
3. Start APEX normally. PCCE schema creation is additive and idempotent.
4. Verify `/api/calibration/status` returns `READY`.
5. Verify `/apex_os/confidence_calibration` loads.
6. Ingest completed-outcome observations only after the corresponding prediction is final and immutable.

## Rollback
1. Redeploy the prior APEX 15.2 commit or repository package.
2. The two additive calibration tables may remain; APEX 15.2 does not depend on them.
3. Do not delete calibration records unless an approved data-retention process requires it.

No broker, execution, recommendation, or production-confidence path is changed by this sprint.
