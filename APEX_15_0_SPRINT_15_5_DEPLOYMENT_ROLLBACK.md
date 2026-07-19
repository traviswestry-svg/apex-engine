# APEX 15.0 Sprint 15.5 Deployment and Rollback

## Deploy
1. Back up the production database and current release artifact.
2. Deploy the complete Sprint 15.5 repository.
3. Install `requirements.txt`.
4. Start APEX normally; additive tables initialize idempotently.
5. Verify `/api/research-lab/status` and `/apex_os/research_lab` return HTTP 200.
6. Confirm `production_effect` is `NONE` and automatic promotion is disabled.

## Rollback
1. Restore the previous Sprint 15.4 application artifact.
2. The four additive Sprint 15.5 tables may remain; Sprint 15.4 does not reference them.
3. To remove them, back up first, then drop only `research_candidates`, `research_runs`, `alpha_attribution_records`, and `promotion_readiness_assessments`.
4. Re-run the prior release smoke tests.
