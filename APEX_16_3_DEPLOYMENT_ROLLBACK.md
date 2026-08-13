# APEX 16.3 Deployment and Rollback

## Deployment
1. Back up the current Render environment and database.
2. Deploy the complete APEX 16.3 repository or merge the changed-files package into APEX 16.2.
3. Keep existing environment variables unchanged.
4. Start the application; schema initialization creates `portfolio_risk_snapshots` idempotently.
5. Verify `/api/portfolio-risk/status`, `/api/mission-control/dashboard?symbol=SPX`, and `/apex_os/mission_control`.
6. Confirm `production_effect` is `NONE` and broker/order mutation flags remain false.

## Rollback
1. Redeploy the prior APEX 16.2 repository.
2. The new table may remain safely because 16.2 does not depend on it.
3. To remove it only after backup, drop `portfolio_risk_snapshots`; no existing APEX tables are altered by 16.3.
