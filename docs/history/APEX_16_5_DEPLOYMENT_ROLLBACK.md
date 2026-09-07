# APEX 16.5 Deployment and Rollback

## Deploy on Render/GitHub
1. Back up the active database and current APEX 16.4 deployment.
2. Replace the repository with the complete APEX 16.5 repository or apply the changed-files package.
3. Commit and push to the deployment branch used by Render.
4. Allow Render to install the existing project requirements and restart the service.
5. Verify `/api/performance-intelligence/status`, `/api/performance-intelligence/dashboard?symbol=SPX`, and `/apex_os/mission_control`.
6. Begin recording only completed outcomes through `/api/performance-intelligence/observations`.

The database tables are created idempotently at runtime. No destructive migration is included.

## Rollback
1. Restore the prior APEX 16.4 commit or repository ZIP.
2. Redeploy on Render.
3. The two new Performance Intelligence tables may remain unused; they do not alter existing tables or live behavior.
4. Restore the pre-deployment database backup only if operational policy requires an exact database rollback.
