# APEX 15.0 Sprint 15.4 — Deployment and Rollback

## Deploy
1. Back up the current Render environment and database.
2. Replace the repository with the complete Sprint 15.4 package or apply the changed-files package.
3. Preserve existing environment variables.
4. Deploy through the existing GitHub-to-Render workflow.
5. Verify `/api/execution-intelligence/status` returns HTTP 200.
6. Verify `/apex_os/execution_intelligence` loads.
7. Submit only completed-trade records; do not connect this research API to live broker order mutation.

## Rollback
1. Redeploy the prior Sprint 15.3 commit/package.
2. The new tables are additive and may remain unused safely.
3. To fully remove Sprint 15.4 data, back up the DB and drop `execution_intelligence_records` and `execution_intelligence_analyses` only after confirming no dependent reporting uses them.
