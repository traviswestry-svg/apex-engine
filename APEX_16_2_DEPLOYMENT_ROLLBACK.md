# APEX 16.2 Deployment and Rollback

## Deployment

1. Back up the current Render deployment and governance database.
2. Deploy the complete APEX 16.2 repository or merge the changed-files package.
3. Preserve existing environment variables.
4. Restart the Render service.
5. Verify:
   - `/api/trade-management/status`
   - `/api/mission-control/dashboard?symbol=SPX`
   - `/apex_os/mission_control`
6. Confirm the status payload reports advisory-only operation and `production_effect: NONE`.

The additive SQLite table is created automatically and may be initialized repeatedly.

## Rollback

1. Redeploy the prior APEX 16.1 commit or repository ZIP.
2. Restart the Render service.
3. The additive `adaptive_trade_management_events` table may remain safely; APEX 16.1 does not depend on it.
4. Do not delete the table unless its immutable audit history is no longer required and a database backup exists.
