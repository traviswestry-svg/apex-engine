# APEX 18.0.4 Deployment and Rollback

## Deployment

1. Deploy `APEX_18_0_4_complete_repository.zip` through the existing GitHub/Render workflow.
2. Keep all current safety values unchanged. In particular, do not enable `ETRADE_ENABLE_TRADING` or `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED` unless the existing confirmation-gated execution workflow is intentionally being activated.
3. Confirm `/api/configuration/status` returns HTTP 200.
4. Review `/api/configuration/diagnostics`; resolve BLOCKING issues before broker submission is permitted.
5. Confirm `/health`, `/apex_os`, and Trade Command Center continue loading.
6. Verify Mission Control shows deployment identity, scanner state, source readiness, and broker safety without displaying credentials.

No database migration is required.

## Rollback

1. Redeploy the prior APEX 18.0.3 repository artifact.
2. No schema rollback is necessary because 18.0.4 adds no database objects or migrations.
3. Existing Render environment variables may remain present; 18.0.3 will ignore variables it does not consume.
4. Revalidate `/health`, Mission Control, scanner lifecycle, and E*TRADE preview safeguards.

## Fail-closed behavior

A BLOCKING configuration state keeps broker submission unsafe while preserving read-only health and diagnostics access. The release does not automatically turn on trading or modify broker credentials.
