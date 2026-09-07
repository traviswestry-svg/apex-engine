# APEX 16.0 Deployment and Rollback

## Deploy
1. Back up the production database and current Render release.
2. Deploy the complete repository ZIP or merge the changed-files package.
3. Run the normal application start command; schema initialization is additive and idempotent.
4. Verify `/api/order-flow-intelligence/status` returns READY.
5. Verify `/api/trading-desk/status` and `/apex_os/institutional_trading_desk` return HTTP 200.
6. Keep IOFI advisory-only while validating live source normalization.

## Rollback
1. Redeploy the prior APEX 15.5 release.
2. The two new IOFI tables may remain safely; older code does not consume them.
3. Do not delete immutable pressure history unless required by a formal data-retention action.
