# APEX 14.0 Sprint 10.2 Deployment and Rollback

## Deployment
1. Back up the production database.
2. Deploy the complete repository.
3. Install existing repository requirements.
4. Start APEX normally; schema initialization is additive and idempotent.
5. Verify `/api/decision-intelligence/confidence/status` and `/apex_os/confidence_attribution`.

## Rollback
Rollback application code to Sprint 10.1. The added table can remain safely because Sprint 10.1 does not read it. For a strict database rollback, restore the pre-deployment database backup.

## Operational impact
No recommendation, confidence, risk, execution, champion, canary, or release-management behavior is changed.
