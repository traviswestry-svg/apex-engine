# APEX 66.2.2 — Deployment & Rollback

## Deploy
1. Upload the changed-files package into the existing APEX GitHub repository, preserving repository paths.
2. Commit with: `APEX 66.2.2 — Historical Level Lifecycle Semantics`.
3. Keep Render Build Command: `pip install -r requirements.txt`.
4. Keep Render Start Command: `./start_render.sh`.
5. Perform a normal deploy. A build-cache clear is not required by this release.
6. Do not delete or recreate `/data` or any production SQLite database.

## Validate
After deployment, authenticate and inspect:
- `/api/system/version`
- `/api/learning/evidence-readiness`
- `/api/learning/evidence-readiness?session_date=2026-08-07`
- `/api/level-calibration/active-levels/diagnostics?session_date=2026-08-07`

For Friday 2026-08-07, verify that historical registration counts are separated from current active counts and that families with registered Friday levels no longer report `unavailable=true` merely because they are retired now.

## Rollback
1. Revert the APEX 66.2.2 Git commit.
2. Redeploy APEX 66.2.1.
3. Do not roll back or replace production databases.

## Database
No schema migration or data mutation is introduced by 66.2.2; database rollback is unnecessary.
