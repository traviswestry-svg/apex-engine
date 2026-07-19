# APEX 16.9 Deployment and Rollback

## Deployment
1. Back up the current Render database and environment variables.
2. Deploy the complete repository ZIP or merge the changed-files package into the 16.8 baseline.
3. Leave `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=false` for initial deployment.
4. Confirm database initialization and API health.
5. Validate E*TRADE sandbox preview payloads before considering submission enablement.
6. Enable submission only in Render after sandbox validation by setting `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=true` and retaining the broker adapter's own trading gate.

## Required production controls
- E*TRADE credentials remain only in Render environment variables.
- Explicit confirmation remains mandatory.
- Live Operations must report TRADEABLE or TRADEABLE_WITH_CAUTION.
- Portfolio Risk must permit new entries.
- Broker Sync must be SYNCED or approved PARTIAL with no blocking discrepancy.

## Rollback
1. Set `APEX_CONFIRMATION_GATED_EXECUTION_ENABLED=false` immediately.
2. Redeploy APEX 16.8.
3. Preserve the 16.9 execution audit tables; they are additive and do not need deletion.
4. Verify Mission Control and broker synchronization endpoints.
