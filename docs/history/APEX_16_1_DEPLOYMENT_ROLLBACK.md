# APEX 16.1 Deployment and Rollback

## Deploy on GitHub + Render
1. Back up the currently deployed repository and database.
2. Replace the repository with the complete 16.1 package, or apply the changed-files package at repository root.
3. Commit and push to the Render-connected branch.
4. Deploy using the existing Render build/start commands.
5. Verify:
   - `/api/mission-control/status`
   - `/api/mission-control/dashboard?symbol=SPX`
   - `/apex_os/mission_control`
6. Confirm the safety payload reports `production_effect: NONE`.

No destructive migration is introduced.

## Rollback
1. Revert the 16.1 commit or redeploy the prior APEX 16.0 commit.
2. No database rollback is required because Mission Control adds no persistent schema.
3. Verify `/api/trading-desk/dashboard` and the original APEX 16.0 deployment.
