# APEX 17.0 Deployment and Rollback

## Deploy
1. Back up the current Render service and database.
2. Replace the repository with the complete 17.0 package or merge the changed-files package.
3. Keep `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=false` during initial deployment.
4. Keep `ETRADE_ENABLE_TRADING=false` unless running a separately approved sandbox test.
5. Deploy through GitHub/Render.
6. Verify `/api/autonomous-desk/status` and `/api/autonomous-desk/dashboard` return HTTP 200.
7. Verify Mission Control loads and reports human confirmation required.
8. Create only a test lifecycle first and validate state transitions without broker submission.

## Rollback
1. Disable execution-related environment flags.
2. Redeploy the APEX 16.9.2 repository.
3. The new 17.0 tables may remain; earlier releases do not depend on them.
4. Restore the database backup only if operational policy requires removal of 17.0 audit records.
