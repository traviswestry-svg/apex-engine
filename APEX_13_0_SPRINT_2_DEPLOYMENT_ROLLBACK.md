# APEX 13.0 Sprint 2 — Deployment and Rollback

## GitHub and Render
Extract the complete repository, replace the repository contents, preserve secrets, commit, push, and deploy through Render. No new external service is required. Configure `APEX_EVIDENCE_DB` on persistent storage so evidence and quality assessments survive deploys. Smoke-test `/api/data-quality/status` and `/apex_os/data_quality`.

## Additive database objects
- `data_quality_schema`
- `data_quality_assessments`
- `data_quality_incidents`

Existing ledger and evidence tables are unchanged.

## Rollback
Redeploy the Sprint 1 commit or ZIP. The new additive tables may remain because prior code ignores them. Back up the evidence database before any optional table removal.
