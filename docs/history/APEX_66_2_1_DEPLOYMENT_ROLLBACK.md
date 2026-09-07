# APEX 66.2.1 Deployment / Rollback

## Deploy
1. Commit the changed files to the existing APEX GitHub repository.
2. Confirm Render Build Command remains `pip install -r requirements.txt`.
3. Confirm Render Start Command remains `./start_render.sh`.
4. Deploy the main branch.
5. Verify `/api/system/version` reports `66.2.1`.
6. Verify `/api/learning/evidence-readiness` reports both `requested_date` and `effective_session_date`.
7. On a non-trading day, verify the automatic effective session resolves to the most recent persisted trading session.
8. Verify `?session_date=YYYY-MM-DD` inspects that exact historical session.

## Rollback
Revert the 66.2.1 application commit and redeploy. No database rollback is required because this release is read-only with respect to persistence and adds no schema changes.
