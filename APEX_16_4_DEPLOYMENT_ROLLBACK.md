# APEX 16.4 Deployment and Rollback

## Deployment
1. Back up the current Render environment and persistent database.
2. Deploy the complete APEX 16.4 repository to the GitHub branch used by Render.
3. Preserve all existing environment variables and persistent-disk configuration.
4. Run the existing application start command.
5. Verify `/api/explainable-intelligence/status` and `/apex_os/mission_control`.
6. Confirm the assistant returns evidence citations and does not alter recommendations or broker state.

The database migration is additive and idempotent. It creates `explainable_intelligence_interactions` when first initialized.

## Rollback
1. Redeploy the prior APEX 16.3 commit or repository ZIP.
2. The additive 16.4 table may remain; APEX 16.3 does not depend on it.
3. Restore the database backup only if organizational policy requires complete schema rollback.
