# APEX 14.0 Sprint 10.4 Deployment and Rollback

## Deploy
1. Back up the current Render environment and persistent database.
2. Replace the repository with the Sprint 10.4 complete repository.
3. Preserve existing environment variables and persistent disk configuration.
4. Deploy through the existing GitHub-to-Render workflow.
5. Verify `/api/dic/status` returns `READY`.
6. Verify `/apex_os/decision_intelligence_center` renders.

No destructive database migration is introduced by Sprint 10.4.

## Rollback
Redeploy the Sprint 10.3 repository. The Sprint 10.4 center is read-only and adds no required destructive state, so rollback does not require data conversion.
