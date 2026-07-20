# APEX 24.1 Deployment and Rollback

## Deployment

Deploy the complete repository using the existing Render build and start
commands. No environment-variable change is required to run.

### Optional governed risk-budget variables

APEX 24.1 reads its portfolio-risk limits from Configuration Governance. When
unset, governed defaults are used and reported as `GOVERNED_DEFAULT`. To override
in production, set any of:

- `APEX_DAILY_RISK_BUDGET` (default 1500)
- `APEX_WEEKLY_RISK_BUDGET` (default 4500)
- `APEX_MONTHLY_DRAWDOWN_LIMIT` (default 9000)
- `APEX_MAX_CONCURRENT_POSITIONS` (default 3)
- `APEX_MAX_PREMIUM_AT_RISK` (default 3000)
- `APEX_MAX_DIRECTIONAL_BIAS_PCT` (default 60)
- `APEX_MAX_PORTFOLIO_HEAT_PCT` (default 35)

Existing `ACCOUNT_SIZE` and `MAX_RISK_PER_TRADE` are reused.

### Startup behaviour

The Portfolio Intelligence surface is required. If its module cannot import, or
any canonical route cannot register (including duplicate-route conflicts),
startup now raises `RuntimeError` and fails loudly rather than silently dropping
the routes.

## Database

No new tables. APEX 24.1 reuses the 16.3 `portfolio_risk_snapshots` table for
`/api/portfolio-risk/record` and `/history`.

## Rollback

Redeploy the previous APEX 24.0 release. No destructive rollback migration is
required. Note that after rollback the legacy 16.3 `/status` and `/evaluate`
handlers (in `institutional_roadmap_routes.py`) are restored automatically with
the older code, since the APEX 24.1 versions live in separate modules.
