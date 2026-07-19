# APEX 18.0.3 — Operational Observability

## Objective

Make `/health` trustworthy during both live and closed sessions by separating status-generation freshness, scan freshness, scanner heartbeat, deployment identity, and source observability.

## Changes

- Runtime version advanced to `11.0.1_OPERATIONAL_OBSERVABILITY`.
- `/health.updated_at` is now guaranteed non-null.
- Added `updated_at_basis` to distinguish `last_completed_scan` from `status_generated_at`.
- Added `status_generated_at`, `health_age_seconds`, `process_started_at`, and `process_uptime_seconds`.
- Added scanner heartbeat, heartbeat age, thread state, scan start, last scan time, scan age, duration, and last error.
- Added authoritative deployment metadata: application version, semantic version, build ID, Git SHA, environment, deployed time, database version, and migration status.
- Added `source_health` records with availability, latency, success time, quote age, and error fields.
- Missing source measurements remain `null`; APEX does not invent zero latency or freshness.
- Preserved the legacy Boolean `sources` map for backward compatibility.
- Release metadata now supports `APEX_DEPLOYED_AT` and `RENDER_DEPLOY_CREATED_AT`.

## Files changed

- `app.py`
- `engine/release_manager.py`
- `tests/test_operational_health.py`
