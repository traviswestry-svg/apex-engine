# APEX Service Dependency Reference

| Dependency | Category | Criticality | Credentials (names only) | Default timeout | Retries | Circuit threshold | Recovery | Failover behavior |
|---|---|---:|---|---:|---:|---:|---:|---|
| database | Database | Critical | DATABASE_URL / DB_PATH | 5s | 1 | 3 | 30s | Local DB_PATH fallback supported |
| polygon_massive | Market data | Critical | POLYGON_API_KEY / MASSIVE_API_KEY | 8s | 2 | 4 | 45s | Configured alternate source |
| quantdata | Market data | Important | QUANTDATA_API_KEY / QUANTDATA_TOKEN | 8s | 2 | 4 | 60s | Reduced flow completeness |
| benzinga | News | Optional | BENZINGA_API_KEY / BENZINGA_TOKEN | 8s | 1 | 4 | 120s | Continue without provider news |
| telegram | Messaging | Optional | TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | 8s | 1 | 4 | 120s | Retain alerts in app surfaces |
| etrade | Broker | Safety critical | ETRADE credential variable names | 10s | 0 | 2 | 120s | Fail closed; no mutation |
| render_runtime | Deployment | Important | APEX_BUILD_ID / RENDER_DEPLOY_ID | 1s | 0 | 3 | 60s | Unknown metadata allowed |
| scanner | Scanner | Critical | None | 30s | 0 | 3 | 60s | Scanner health warning/blocking assessment |

Secret values are never returned by dependency APIs.
