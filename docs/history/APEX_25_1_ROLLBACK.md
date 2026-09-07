# APEX 25.1 Rollback

To roll back to APEX 25.0:

1. Revert the 25.1 deployment commit.
2. Redeploy the prior Render commit.
3. Confirm `/api/decision-integrity/status` remains available.

The two new engine files and two new test files can be removed during rollback. No database rollback is needed.
