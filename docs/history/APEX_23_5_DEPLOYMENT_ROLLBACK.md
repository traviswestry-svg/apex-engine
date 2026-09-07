# APEX 23.5 Deployment and Rollback

## Deploy
Deploy the complete repository with the existing Render build/start commands. No new required environment variables are introduced.

## Persistence
Coach reviews use the existing `DB_PATH`. On Render, ensure `DB_PATH` resolves to persistent storage if review history must survive redeployments.

## Rollback
Redeploy the APEX 23.4 complete repository. The new `apex_coach_reviews_v235` table is isolated and can remain in the database; older releases ignore it.
