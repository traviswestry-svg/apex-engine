# APEX 18.0.1 Deployment and Rollback

## Deploy on Render/GitHub

1. Back up the current APEX 18.0 branch or create a release tag.
2. Apply the changed-files package at the repository root, or replace the repository with the complete package.
3. Commit and push to GitHub.
4. Allow Render to deploy.
5. Keep `ETRADE_ENABLE_TRADING=false` during initial validation.
6. Open `/apex_os/trade_command`.
7. Select an expiration and verify **Arm Plan** populates every leg.
8. Verify unresolved/stale legs display `ARMED EXECUTION BLOCKED`.
9. Verify a valid strategy reaches E*TRADE preview in sandbox.
10. Only enable placement after sandbox preview and confirmation testing is complete.

## Rollback

Restore the APEX 18.0 tag/commit or redeploy `APEX_18_0_complete_repository.zip`. No destructive database migration is required by 18.0.1.

## Required safety settings

```text
ETRADE_ENV=sandbox
ETRADE_ENABLE_TRADING=false
human confirmation required
```
