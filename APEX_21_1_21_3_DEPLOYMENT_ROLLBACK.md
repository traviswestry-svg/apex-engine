# APEX 21.1–21.3 Deployment and Rollback

## Deployment
1. Deploy the complete repository package through the existing GitHub/Render workflow.
2. Do not change trading or broker environment variables for this release.
3. Confirm `/health` returns HTTP 200 and version `14.3.0_INSTITUTIONAL_MISSION_CONTROL_2`.
4. Confirm `/apex_os` renders the Institutional Decision Banner and the three compact workspace cards.
5. Confirm the seven new read-only API routes return HTTP 200.

## Rollback
1. Redeploy the last verified APEX 20.3 repository/commit.
2. No database rollback is required.
3. No environment-variable removal is required.
4. Verify `/health`, `/apex_os`, Trade Command, and broker preview safeguards after rollback.

The release is declarative and read-only; it introduces no migrations or broker mutations.
