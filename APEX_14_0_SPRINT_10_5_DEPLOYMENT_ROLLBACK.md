# APEX 14.0 Sprint 10.5 — Deployment and Rollback

## GitHub → Render deployment
1. Back up the existing Render database and environment variables.
2. Upload the complete repository contents to the deployment branch.
3. Commit and push.
4. Allow Render to build and restart using the existing service configuration.
5. Verify `/api/replay2/status` and `/apex_os/institutional_replay`.
6. Build a replay only after a Sprint 10.1 decision record exists.

The database migration is additive and idempotent.

## Rollback
Redeploy the prior Sprint 10.4 commit or ZIP. The new `institutional_replays` table may remain unused; no existing production table or decision behavior must be reverted.
