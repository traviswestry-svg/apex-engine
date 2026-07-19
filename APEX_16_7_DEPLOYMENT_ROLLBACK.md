# APEX 16.7 Deployment and Rollback

## Deployment
1. Back up the current database and Render environment variables.
2. Deploy the complete 16.7 repository to GitHub.
3. Allow Render to build using the existing repository command.
4. Verify `/api/strategy-promotion/status` returns READY.
5. Verify `/api/mission-control/dashboard` contains `strategy_promotion`.
6. Submit candidates only through the governed API or approved internal workflow.

Database tables are created idempotently on first engine initialization.

## Rollback
1. Redeploy the APEX 16.6 repository or prior stable Git commit.
2. The three 16.7 tables may remain; older code does not depend on them.
3. Do not delete governance records unless a separately approved retention procedure requires it.

## Safety
Approval does not deploy or enable a strategy. Production activation remains a separate manual operation.
