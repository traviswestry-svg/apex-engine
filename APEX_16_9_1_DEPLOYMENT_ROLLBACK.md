# APEX 16.9.1 Deployment and Rollback

## Deploy on GitHub + Render
1. Back up the current 16.9 branch or tag.
2. Replace the repository with the 16.9.1 complete package, or apply the changed-files package.
3. Keep `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=false` during deployment.
4. Keep E*TRADE configured for sandbox, never production.
5. Deploy through Render and verify the status and dashboard endpoints.
6. Run the sandbox certification using actual E*TRADE sandbox responses.
7. Do not enable execution until the certification result is reviewed and explicitly approved.

## Required safeguards
- `ETRADE_ENV=sandbox`
- `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=false` before the manual test window
- Human confirmation required
- No credentials committed to GitHub

## Rollback
Redeploy the prior APEX 16.9 commit or repository ZIP. The new tables are additive and can remain without affecting 16.9.
