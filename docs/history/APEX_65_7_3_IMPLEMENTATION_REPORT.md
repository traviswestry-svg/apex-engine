# APEX 65.7.3 — Scanner Startup / Heartbeat Fix

## Live finding
65.7.2 deployed correctly at the HTTP layer, but `/data/scanner_heartbeat.json` remained absent while Gunicorn continued serving requests. Because 65.7.2's `start_render.sh` explicitly terminates the web process if `scanner_worker.py` exits, the observed production state proves the effective Render start path can bypass `start_render.sh` (for example, a dashboard Start Command override that launches Gunicorn directly).

## Root cause
APEX had only one deployment path capable of starting `scanner_worker.py`: `start_render.sh`. A direct Gunicorn launch through `wsgi:app` created a healthy web process with no scanner process, no scanner heartbeat, and therefore no scanner-owned HLCE collector.

## Repairs
1. **Direct-Gunicorn fail-safe** — `wsgi.py` calls `ensure_scanner_process()` after composing Flask. In Render/production, if the scanner is not marked externally managed, a separate `scanner_worker.py` subprocess is started.
2. **No duplicate when shell launcher is active** — `start_render.sh` exports `APEX_SCANNER_MANAGED_EXTERNALLY=true` before launching Gunicorn. The WSGI fallback sees this and does not spawn another scanner.
3. **WSGI supervisor lease** — only one WSGI worker can own subprocess supervision, making the fallback safe if worker count changes later.
4. **Canonical scanner process lease before app import** — `scanner_worker.py` acquires the existing scanner lease before importing the large application. This is the final defense against duplicate scanner/HLCE ownership.
5. **Bootstrap heartbeat** — the scanner writes `/data/scanner_heartbeat.json` with `phase=IMPORTING_APP` before `app.py` imports, then `STARTING`, then `RUNNING`. If app import fails, it records `phase=APP_IMPORT_FAILED` and the exception before exiting.
6. **Child watchdog** — direct-Gunicorn mode restarts the scanner subprocess if it exits and no fresh scanner heartbeat belongs to another owner.
7. **Operational visibility** — HLCE status/health now includes `web_scanner_supervisor` diagnostics in addition to the cross-process scanner heartbeat.

## Expected production signatures
### If Render uses `start_render.sh`
- `scanner_heartbeat.bootstrap_source: start_render`
- `web_scanner_supervisor.managed_externally: true`
- `collector_owner: scanner_process`
- `collector_running: true` once HLCE starts

### If Render launches Gunicorn directly
- `scanner_heartbeat.bootstrap_source: wsgi_supervisor`
- `web_scanner_supervisor.owner: true`
- `web_scanner_supervisor.child_alive: true`
- `collector_owner: scanner_process`
- `collector_running: true`

In both modes `/data/scanner_heartbeat.json` must exist within startup time. During RTH, `daily_levels` and `price_samples` should then begin increasing if the HLCE provider receives live context.

## Validation
- `bash -n start_render.sh` — PASS
- Python compile (`wsgi.py`, `scanner_worker.py`, supervisor, calibration routes) — PASS
- APEX 65.7 integrity + HLCE + LTPE targeted regression set — **43/43 PASS**
