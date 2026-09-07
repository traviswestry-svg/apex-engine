# APEX 13.0 Sprint 9A — Deployment and Rollback

## Deployment
1. Commit or upload the complete repository to GitHub.
2. Deploy through Render using the existing service configuration.
3. Confirm `/api/production/status` returns HTTP 200.
4. Confirm `/apex_os/production_governance` renders.
5. Do not treat `QUEUED_NOT_DEPLOYED` as activation; Sprint 9A contains no deployment controller.

## Rollback
1. Redeploy the prior Sprint 8 commit or ZIP.
2. The new SQLite tables are additive and may remain; older code ignores them.
3. No live production configuration is modified by Sprint 9A, so application rollback does not require restoring trading weights or recommendation policies.
