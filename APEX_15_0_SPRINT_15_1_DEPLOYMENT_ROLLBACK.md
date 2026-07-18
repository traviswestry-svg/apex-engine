# Deployment and Rollback — APEX 15.0 Sprint 15.1

## Deployment
1. Upload the complete repository to GitHub or merge the changed-files package into the Sprint 10.6 baseline.
2. Commit and push to the branch monitored by Render.
3. Allow Render to install the existing requirements and start the existing application command.
4. Verify `/api/imse/status` returns `READY`.
5. Open `/apex_os/institutional_market_state`.

The migration is additive and idempotent. IMSE tables are created on initialization.

## Rollback
Revert the Sprint 15.1 commit and redeploy the Sprint 10.6 repository. The additive IMSE tables may remain without affecting prior code. Do not delete database tables during an emergency rollback.
