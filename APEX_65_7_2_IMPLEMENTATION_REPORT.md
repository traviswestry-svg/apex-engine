# APEX 65.7.2 — HLCE Collector Lifecycle Repair

## Live finding
The web-served `/api/level-calibration/status` showed `collector_running:false` after 65.7. That local value is expected because 65.7 intentionally removed the HLCE daemon from Gunicorn. The real defect was that shared calibration counts remained zero during RTH, meaning scanner-owned ingestion was not producing evidence.

## Repairs
1. **Scanner lifecycle self-healing** — `scanner_worker.py` now verifies the scanner-owned HLCE thread at startup and on every heartbeat cycle. A failure to start/recover is fatal to the scanner process rather than silently leaving calibration dead.
2. **Provider fallback** — live SPX acquisition first uses the v3 index snapshot, then falls back to APEX's existing `I:SPX` intraday aggregate path. No synthetic price is fabricated.
3. **Immediate evidence probe** — startup/recovery performs one synchronous HLCE tick when a valid snapshot is available, so provider disconnects become visible immediately.
4. **Cross-process diagnostics** — scanner heartbeat now publishes collector running state, provider health/error, provider source, DB path, DB counts, and restart count.
5. **Render process supervision** — `start_render.sh` now treats both Gunicorn and `scanner_worker.py` as required. If either process exits, the service exits so Render restarts the pair. Previously the scanner could die while Gunicorn continued serving HTTP.
6. **Owner-aware calibration status** — `/api/level-calibration/status` and `/health` semantics are no longer confused by the intentionally idle web-local HLCE singleton. Calibration status reads the fresh scanner heartbeat and exposes `collector_owner`, `local_web_collector_running`, and `collector_status_source`.

## Acceptance after deploy
During RTH, `GET /api/level-calibration/status` should show:
- `collector_owner: scanner_process`
- `collector_running: true`
- `local_web_collector_running: false`
- fresh `scanner_heartbeat`
- `scanner_heartbeat.hlce_provider_ok: true`
- `database.counts.daily_levels > 0`
- `database.counts.price_samples > 0`
- `last_database_write != null`

Interactions/outcomes may remain zero until a level is encountered and the grading horizon matures.

## Validation
- `bash -n start_render.sh` — PASS
- Python compile — PASS
- targeted HLCE/LTPE/integrity regression set — **33/33 PASS**
