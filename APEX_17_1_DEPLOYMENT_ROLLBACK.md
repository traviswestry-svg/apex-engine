# APEX 17.1 Deployment and Rollback

## Deployment
1. Back up the currently deployed repository and database.
2. Deploy the complete repository or apply the changed-files package at repository root.
3. Keep all existing Render environment variables unchanged.
4. Redeploy or restart the Render service.
5. Verify:
   - `/api/trading-desk-ux/status`
   - `/api/trading-desk-ux/workspace?symbol=SPX`
   - `/apex_os/institutional_trading_desk`
6. Hard-refresh the browser with `Ctrl + F5` so the redesigned template is loaded.
7. Confirm the ribbon, timeline, Evidence Explorer, broker panel, and Explainable Intelligence render.

## Rollback
1. Restore the APEX 17.0 repository.
2. Redeploy the Render service.
3. No database rollback is required; 17.1 adds no database tables or destructive migrations.
4. Browser-only preferences may be cleared from browser site data if desired.

## Safety
Do not enable automatic execution as part of this deployment. Existing E*TRADE confirmation and kill-switch settings remain authoritative.
