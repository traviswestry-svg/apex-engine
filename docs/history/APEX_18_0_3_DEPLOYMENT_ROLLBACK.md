# APEX 18.0.3 — Deployment and Rollback

## Deploy

1. Replace the GitHub repository contents with the complete package or apply the changed-files package.
2. Commit and push to the production branch used by Render.
3. Set these optional Render environment values for the strongest release identity:
   - `APEX_BUILD_ID`
   - `APEX_GIT_COMMIT` (Render's `RENDER_GIT_COMMIT` is also supported)
   - `APEX_DEPLOYED_AT` (or `RENDER_DEPLOY_CREATED_AT`)
   - `APEX_ENVIRONMENT=production`
   - `APEX_DATABASE_SCHEMA_VERSION=5`
4. Deploy and verify `/health`.
5. Confirm `version` is `11.0.1_OPERATIONAL_OBSERVABILITY` and `updated_at` is non-null.

## Rollback

Revert the three changed code/test files to the APEX 18.0.2 versions and redeploy. No database migration or data rollback is required.
