# APEX 18.0.5 Deployment and Rollback

## Deploy
1. Deploy the complete repository package through the existing GitHub/Render workflow.
2. Do not change trading, confirmation, or broker-mutation environment variables.
3. Verify `/health`, `/api/configuration/status`, and `/api/dependencies/status` return HTTP 200.
4. Open Mission Control and confirm Configuration Health and Dependency Health render.

## Rollback
Redeploy the last known-good APEX 18.0.4 commit/package. No database migration or data rollback is required. The new dependency registry and circuit state are in-memory only.
