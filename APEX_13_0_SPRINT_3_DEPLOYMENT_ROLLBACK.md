# APEX 13.0 Sprint 3 Deployment and Rollback

## GitHub / Render deployment
1. Back up the persistent Render disk containing the ledger, evidence, and governance SQLite databases.
2. Commit or upload the complete repository contents to the production GitHub branch.
3. Confirm existing Render environment variables and persistent-disk mount paths remain unchanged.
4. Deploy through the existing Render service.
5. Verify `/api/historical-readiness/status`, `/api/historical-readiness/report`, and `/apex_os/historical_readiness`.
6. Confirm the status remains honest (`COLLECTING`, `INSUFFICIENT_HISTORY`, or `DEGRADED_HISTORY`) until all gates pass.

## Optional threshold environment variables
- `APEX_HISTORY_MIN_GRADED` — default follows the governance minimum, currently 50.
- `APEX_HISTORY_MIN_ELIGIBLE` — default 25.
- `APEX_HISTORY_MIN_DATE_DAYS` — default 20.
- `APEX_HISTORY_MAX_EXCLUSION_RATE_PCT` — default 25.

## Rollback
1. Redeploy the previous Sprint 2 commit or ZIP.
2. No database rollback is required because Sprint 3 adds no tables and performs no destructive migration.
3. The Sprint 3 module and routes can be removed without altering ledger, evidence, quality, outcome, vector, candidate, or audit history.
