# Deployment and Rollback — Sprint 15.2

## Deploy
1. Back up the production database and current Render deployment.
2. Replace the repository with the complete Sprint 15.2 package or merge the changed-files package.
3. Push to GitHub and allow Render to deploy.
4. Confirm `/api/playbooks/status` returns `READY`.
5. Confirm `/apex_os/playbook_engine` loads.
6. Run a non-persistent `/api/playbooks/evaluate` request before recording live snapshots.

Database changes are additive and created idempotently on initialization.

## Rollback
1. Redeploy the prior APEX 15.1 commit/package.
2. The new playbook tables may remain; prior code does not depend on them.
3. Do not delete tables during an emergency rollback. Archive them later only after validation.
