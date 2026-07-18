# APEX 14.0 Sprint 10.6 — Deployment and Rollback

## GitHub-to-Render deployment

1. Back up the currently deployed Sprint 10.5 commit.
2. Extract the complete Sprint 10.6 repository package.
3. Commit and push the repository contents to the deployment branch.
4. Allow Render to build and deploy normally.
5. Verify `/api/cross-examination/status` returns `READY`.
6. Verify `/api/cross-examination/questions` returns the deterministic question taxonomy.
7. Verify `/apex_os/cross_examination` renders.
8. Confirm `production_effect` is `NONE` and all mutation flags are false.

The database migration is additive and idempotent. It creates `cross_examination_records` and related indexes without modifying existing Decision Intelligence records.

## Rollback

Redeploy the prior Sprint 10.5 commit or ZIP. The additive `cross_examination_records` table may remain unused; no existing recommendation, replay, governance, or production table requires reversal.
