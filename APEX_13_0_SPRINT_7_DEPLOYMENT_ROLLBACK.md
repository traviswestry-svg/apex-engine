# APEX 13.0 Sprint 7 Deployment and Rollback

## Deployment
1. Replace the repository with the complete Sprint 7 package or merge the changed-files package.
2. Deploy through the existing GitHub-to-Render workflow.
3. Open `/api/learning/optimization/status` and confirm a valid fail-closed status.
4. Open `/apex_os/offline_optimization`.
5. Do not run optimization until real eligible outcomes meet the configured minimum.

Database tables are created idempotently at startup.

## Rollback
1. Redeploy the prior Sprint 6 repository.
2. The new tables may remain safely because Sprint 6 does not query them.
3. No production policy rollback is necessary because Sprint 7 cannot change production behavior.
