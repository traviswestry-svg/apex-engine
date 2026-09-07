# APEX 14.0 Sprint 10.3 Deployment and Rollback Guide

## Deploy

1. Back up the production database.
2. Deploy the complete Sprint 10.3 repository.
3. Allow normal application initialization to create the additive `institutional_evidence_graphs` table.
4. Verify `/api/decision-intelligence/graph/status` returns HTTP 200 and `production_effect: NONE`.
5. Verify `/apex_os/evidence_graph` renders.
6. Build a graph only for an existing Sprint 10.1 decision record.

## Rollback

1. Redeploy the Sprint 10.2 repository.
2. The additive graph table may remain safely unused, or it may be removed after backup during a maintenance window.
3. No recommendation, confidence, execution, champion, canary, or release state requires restoration because Sprint 10.3 is observational only.
