# APEX 20.1–20.3 Deployment and Rollback

## Deployment
1. Deploy the complete repository package or apply the changed-files package to APEX 20.0.
2. Keep all current Render environment variables unchanged.
3. Confirm `/api/system/version` reports `13.3.0_STRATEGY_INTELLIGENCE`.
4. Confirm `/health`, `/apex_os`, and the new decision-suite APIs return HTTP 200.
5. Keep live trading, automatic execution, and broker mutation disabled unless separately authorized under existing safeguards.

## Rollback
Redeploy the prior APEX 20.0 repository. No database rollback is required because this release adds no migration or persistent schema.
