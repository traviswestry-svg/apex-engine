# APEX 13.0 Sprint 8 Deployment and Rollback

## Deploy
1. Back up the Render persistent governance database if configured.
2. Replace the deployed repository with the complete Sprint 8 repository.
3. Deploy through the existing GitHub-to-Render workflow.
4. Verify `/api/learning/shadow-campaigns`, `/api/learning/champion-challenger`, and `/apex_os/shadow_validation`.
5. Do not create a campaign until the candidate is already `SHADOW_ONLY` through Sprint 6 governance.

## Rollback
1. Redeploy the Sprint 7 repository.
2. Sprint 8 tables are additive and may remain in SQLite without affecting Sprint 7.
3. No production configuration requires restoration because Sprint 8 cannot alter it.
4. Archive or pause any active campaign before rollback when operationally possible.
