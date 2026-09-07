# APEX 13.0 Sprint 9B — Deployment and Rollback

## Render deployment
1. Back up the current Render environment and persistent database.
2. Upload the complete Sprint 9B repository to GitHub.
3. Deploy the new commit through Render.
4. Confirm `/api/production/canary/status` returns HTTP 200.
5. Confirm `/apex_os/canary_deployment` renders.
6. Do not start a canary until its Sprint 9A manifest is reviewed.

## Canary rollback
Use `POST /api/production/canaries/<canary_id>/rollback` with an actor and reason. The controller immediately changes the canary to `ROLLED_BACK`; all subsequent routing resolves to the recorded champion.

## Code rollback
Redeploy the prior Sprint 9A Git commit. Sprint 9B tables are additive and do not alter Sprint 9A promotion records or the champion registry.
