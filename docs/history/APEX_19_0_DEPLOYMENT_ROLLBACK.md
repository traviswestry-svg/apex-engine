# APEX 19.0 Deployment and Rollback

## Deployment
1. Deploy the complete repository to the existing GitHub/Render service.
2. Do not change trading or broker environment variables for this release.
3. Confirm `/health` and `/api/institutional-intelligence-engine/status` return HTTP 200.
4. Confirm Mission Control renders the Institutional Intelligence strip.
5. During closed market hours, `execution_eligible` may remain false because live evidence is unavailable; this is expected.

## Rollback
Redeploy the previously validated APEX 18.0.5 commit or package. No database rollback is required because APEX 19.0 introduces no schema changes or persistent writes.
