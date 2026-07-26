# APEX 47.0.7 — Runtime Status Truth & Release Authority Repair

## Purpose
Repairs the backend path that continued reporting APEX 25.1.1 after newer frontend builds deployed successfully.

## Root cause
`app.py` imported `APP_VERSION` from `engine/release_manager.py`, where the active product version remained hard-coded as `25.1.1_DECISION_QUALITY`. The same runtime health resolver also evaluated scanner startup before session state, causing an intentionally idle closed-market scanner to report `DEGRADED`.

## Changes
- Canonical product release now loads from `config/apex_release_manifest.json`.
- Active backend version is `47.0.7`.
- Retired 25.1.1 identifiers remain only under `legacy_*` metadata.
- `/health`, `/api/market_status`, and `/api/system/*` inherit the canonical version through the existing backend import chain.
- Closed sessions report `CLOSED` and `SCHEDULED_IDLE` even if the scanner and heartbeat file are absent.
- Live sessions still report `DEGRADED` when the scanner is expected but not running.
- Both `app.py` and the quarantined `engine/app.py` were patched to prevent regression.

## Deployment verification
After Render restarts, `/health` should include:

```json
{
  "apex_version": "47.0.7",
  "version": "47.0.7",
  "health_state": "CLOSED",
  "scanner_expected": false,
  "scanner_state": "SCHEDULED_IDLE"
}
```
