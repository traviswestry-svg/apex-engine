# APEX 65.7.5 — App Entrypoint Scanner Bootstrap Repair

## Production failure addressed
APEX 65.7.4 proved that the deployed service was serving the legacy Flask application while bypassing both the expected WSGI bootstrap and the registered Flask request bootstrap (`ensure_calls=0`, `launches=0`, missing `/data/scanner_heartbeat.json`).

## Root repair
65.7.5 moves the scanner fail-safe to the one production boundary that cannot be bypassed while the current route set is served: `app.py` itself.

After all routes are registered, `app.py` calls `ensure_scanner_process(source="app_module_import")`. This covers direct `gunicorn app:app`, `wsgi:app`, the application factory, and direct `python app.py` execution.

To prevent recursive scanner spawning, `scanner_worker.py` sets `APEX_SCANNER_PROCESS=true` before importing `app.py`. The process supervisor also propagates the same marker into any scanner child it launches. `ensure_scanner_process()` immediately returns without launching when that marker is present.

Existing scanner-process lease protection remains authoritative, so concurrent bootstrap attempts cannot create multiple live scanner/HLCE owners.

## Diagnostics added
The scanner supervisor now exposes:
- `version: 65.7.5_APP_ENTRYPOINT_BOOTSTRAP`
- `last_ensure_source`
- `last_ensure_pid`
- `skipped_scanner_child`

A successful direct production bootstrap should show `last_ensure_source: app_module_import`, `ensure_calls > 0`, and then a scanner heartbeat.

## Validation
- Python compile checks passed for modified runtime modules.
- Targeted APEX 65.7 integrity + HLCE/LTPE regression suite: 53/53 passed.

## Post-deployment acceptance
`GET /api/level-calibration/status` should show:
1. `web_scanner_supervisor.ensure_calls > 0`
2. `web_scanner_supervisor.last_ensure_source = "app_module_import"` (or a later WSGI ensure if wsgi is used)
3. `scanner_heartbeat.available = true`
4. `collector_owner = "scanner_process"`
5. `collector_running = true`
6. `local_web_collector_running = false`
7. during RTH: `daily_levels > 0`, `price_samples > 0`, `last_database_write != null`
