# APEX 65.7.4 — Gunicorn Lifecycle Scanner Bootstrap

## Live defect repaired
Production 65.7.3 diagnostics showed the supervisor module loaded but never attempted scanner startup:

- `enabled: true`
- `managed_externally: false`
- `child_alive: false`
- `child_pid: null`
- `launches: 0`
- `/data/scanner_heartbeat.json` missing

This proved the import-time bootstrap path was not reliable under the deployed Gunicorn lifecycle.

## Changes

### `wsgi.py`
- Retains import-time scanner ensure as a fast path.
- Adds an idempotent Flask `before_request` lifecycle guard.
- The guard executes inside the actual serving Gunicorn worker, closing preload/fork/thread-survival gaps.
- Web still never owns the scanner loop or HLCE collector; it only supervises a separate scanner process.

### `engine/scanner_process_supervisor.py`
- Version: `65.7.4_GUNICORN_LIFECYCLE_BOOTSTRAP`.
- Adds `ensure_calls`, `lease_acquired`, and `lease_error` diagnostics.
- Missing scanner heartbeat now triggers a scanner launch attempt even when the auxiliary supervisor lease cannot be obtained.
- Only the supervisor-lease owner runs the long-lived watchdog.
- Duplicate safety remains enforced by `scanner_worker.py`'s canonical scanner process lease, acquired before importing the application.

## Why this is safe
Multiple web workers may briefly attempt to spawn a scanner only when no valid heartbeat exists. The scanner process itself acquires the canonical cross-process scanner lease before importing `app.py`; losing contenders exit before scanner/HLCE startup. This avoids the prior failure mode where an auxiliary supervisor lock could leave production permanently at `launches: 0`.

## Validation
Targeted suites:

- `tests/test_apex_65_7_integrity.py`
- `tests/test_apex_50_5_0_historical_level_calibration.py`
- `tests/test_apex_50_6_0_level_transition_probability.py`
- `tests/test_apex_50_7_0_transition_learning_activation.py`

Result: **40 passed**.

Python compile checks also passed for the affected startup/scanner/calibration modules.

## Post-deployment acceptance
`/api/level-calibration/status` should show:

- `web_scanner_supervisor.ensure_calls > 0`
- `web_scanner_supervisor.launches >= 1` when no prior scanner heartbeat exists
- `scanner_heartbeat.available: true`
- `collector_running: true`
- `collector_status_source: scanner_heartbeat`
- then `database.counts.daily_levels > 0`
- and `database.counts.price_samples > 0`

`local_web_collector_running` should remain `false`.
