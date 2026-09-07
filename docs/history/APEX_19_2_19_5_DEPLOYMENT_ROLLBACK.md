# APEX 19.2–19.5 Deployment and Rollback

## Deployment
1. Back up the currently deployed APEX 19.1 repository and Render environment variables.
2. Deploy `APEX_19_2_19_5_complete_repository.zip` through the existing GitHub/Render workflow.
3. Confirm `/api/system/version` reports `12.5.0_ADAPTIVE_LEARNING_ENGINE_V2`.
4. Confirm `/health` and `/apex_os` return HTTP 200.
5. Confirm all eight new intelligence endpoints return HTTP 200.
6. Leave live trading, automatic execution, and broker mutation flags unchanged.

## Rollback
1. Redeploy the previously validated APEX 19.1 commit or package.
2. No database rollback is required because this release adds no migration.
3. Confirm the prior runtime identity and health routes.
4. Review Render logs for route-registration errors before attempting redeployment.
