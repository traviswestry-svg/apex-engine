# APEX 16.6 Deployment and Rollback

## Deploy
1. Back up the current Render environment and database.
2. Upload or merge the complete 16.6 repository into GitHub.
3. Confirm existing environment variables remain unchanged.
4. Deploy through Render.
5. Verify `/api/live-operations/status` returns HTTP 200.
6. Verify `/api/live-operations/dashboard?symbol=SPX` returns HTTP 200.
7. Open `/apex_os/mission_control` and confirm the Live Operations panel appears.
8. During market hours, confirm required source timestamps are populated by the live adapters.

## Important integration note
The 16.6 engine accepts source heartbeat/timestamp payloads. Existing provider adapters should submit their real timestamps into `/api/live-operations/evaluate` or the shared Mission Control snapshot. Until live adapters populate them, the gate will honestly classify missing required data as disconnected or stale.

## Rollback
1. Redeploy the prior APEX 16.5 commit or package.
2. The new SQLite tables may remain; they are additive and do not alter prior tables.
3. Confirm Mission Control and prior APIs return HTTP 200.

## Safety
No broker execution, live-order mutation, recommendation replacement, confidence mutation, or automatic strategy changes are enabled.
