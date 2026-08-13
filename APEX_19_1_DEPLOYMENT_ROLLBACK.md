# APEX 19.1 Deployment and Rollback

## Deploy
1. Back up the currently deployed APEX package and Render environment settings.
2. Deploy the complete APEX 19.1 repository.
3. Confirm runtime identity reports `12.1.0_INSTITUTIONAL_MARKET_STRUCTURE_ENGINE`.
4. Verify `/health`, `/apex_os`, and the five market-structure APIs return HTTP 200.
5. Confirm trading remains disabled unless the existing operator-controlled switches are intentionally enabled.

## Rollback
1. Redeploy the prior APEX 19.0 complete repository.
2. No database rollback is required.
3. Verify `/health`, Mission Control, Trade Command Center, and broker preview safeguards.

## Fail-safe behavior
Missing profiles or bars produce a degraded read-only state. Stale data is explicitly flagged and cannot be treated as execution-ready intelligence.
