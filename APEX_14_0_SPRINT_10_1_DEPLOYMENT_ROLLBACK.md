# APEX 14.0 Sprint 10.1 — Deployment and Rollback

## Deployment

1. Deploy the complete repository through the existing GitHub-to-Render workflow.
2. Preserve the existing `APEX_GOVERNANCE_DB` configuration.
3. Start the application normally; schema initialization is additive and idempotent.
4. Verify `GET /api/decision-intelligence/status` returns `READY`.
5. Open `/apex_os/decision_intelligence`.

No provider keys, broker configuration, strategy settings, or production-governance settings are changed.

## Rollback

Re-deploy the prior Sprint 9C repository. The four new tables may remain in SQLite because prior code does not query them. They may also be removed during a maintenance window after preserving a database backup.

Rollback does not require changing the production champion, canary configuration, recommendation logic, or execution controls.
