# APEX 16.8 Deployment and Rollback

## Deploy

1. Back up the current Render environment and database.
2. Deploy the complete APEX 16.8 repository through the existing GitHub-to-Render workflow.
3. Confirm startup and database schema initialization.
4. Verify `/api/broker-sync/status` and `/api/mission-control/dashboard` return HTTP 200.
5. Connect the existing E*TRADE adapter by posting normalized or raw adapter snapshots to `/api/broker-sync/record`.
6. Keep broker credentials and OAuth tokens in Render environment variables; never commit them.

## Important

APEX 16.8 does not independently authenticate to E*TRADE. It provides the governed read-only synchronization contract into which the existing sandbox adapter should publish account, position, order, and fill snapshots.

## Rollback

1. Redeploy the APEX 16.7 release.
2. The two new SQLite tables may remain safely; 16.7 does not consume them.
3. Do not delete immutable broker snapshots unless a separate retention policy is approved.
