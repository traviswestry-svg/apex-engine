# APEX 22.0 Deployment and Rollback

## Deployment
1. Deploy the complete repository normally.
2. Leave `APEX_MARKET_MEMORY_CAPTURE_ENABLED=false` for dormant deployment.
3. Optionally set `APEX_MARKET_MEMORY_DB` to a persistent-disk path on Render before enabling capture.
4. Confirm `/api/market-memory/status` returns `DORMANT` and HTTP 200.
5. Enable capture only after persistent storage is confirmed.

## Recommended dormant settings
```text
APEX_MARKET_MEMORY_CAPTURE_ENABLED=false
APEX_MARKET_MEMORY_OUTCOME_WRITES_ENABLED=false
APEX_MARKET_MEMORY_MIN_SESSIONS=20
```

## Rollback
Redeploy the prior APEX 21.1–21.3 complete repository. The isolated Market Memory SQLite file may be retained for a later redeployment or removed after backup. No existing APEX database schema is altered.
