# APEX 66.2.0 — Deployment & Rollback

## GitHub + Render deployment
1. Commit the APEX 66.2.0 repository as a single release commit.
2. Push to the branch used by the Render production service.
3. Do not change or delete `/data` persistent disks or APEX learning databases.
4. Keep the existing authentication, E*TRADE, scanner, market-data, and risk environment variables unchanged.
5. Allow Render to perform its normal build/start command.
6. Verify `/api/version`, `/api/release-manifest`, `/api/level-calibration/status`, `/api/level-calibration/active-levels/diagnostics`, and `/api/learning/evidence-readiness`.
7. Do not enable live E*TRADE execution solely for validation. Validate in the currently configured broker mode.

## Rollback
If APEX 66.2.0 introduces a production regression:
1. Roll Render back to the immediately preceding known-good repository commit/build (the uploaded repository implements through 66.1.2 component work).
2. Do not roll back, delete, truncate, or replace durable SQLite learning stores.
3. Preserve `/data` and all database sidecars.
4. Restore the prior application image/code only.
5. Re-verify scanner heartbeat, HLCE collector ownership, canonical active-level synchronization, authentication, and broker mode before resuming normal operation.

No database down-migration is required because APEX 66.2.0 adds no database schema.
