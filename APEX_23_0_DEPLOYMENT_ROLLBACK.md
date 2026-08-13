# APEX 23.0 Deployment and Rollback

## Deployment

Deploy the complete repository through the existing GitHub/Render workflow. No database migration is required. Existing environment variables remain valid.

Market Memory calibration uses the existing governed settings:

- `APEX_MARKET_MEMORY_DB`
- `APEX_MARKET_MEMORY_MIN_SESSIONS`
- `APEX_MARKET_MEMORY_CAPTURE_ENABLED`
- `APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED`

Capture and outcome writes may remain disabled. The Trading Brain still operates using current-session evidence and reports calibration as dormant.

## Post-deployment checks

Confirm HTTP 200 from:

- `/health`
- `/api/trading-brain/status`
- `/api/trading-brain/diagnostics`
- `/api/mission-control-v2/status`

Confirm the release version is `16.0.0_INSTITUTIONAL_TRADING_BRAIN`.

## Rollback

Redeploy the previously validated APEX 22.5 repository. No database downgrade or schema rollback is necessary because APEX 23.0 introduces no database schema changes and performs no automatic configuration mutation.
