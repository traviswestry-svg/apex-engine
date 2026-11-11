# APEX 69.10.47 — Production Memory Pressure Containment Candidate

## Evidence and urgency

November 11 2026 12:19 ET snapshot: 4,262,830,080 / 4,294,967,296 bytes (99.25%), approximately 32.1 MB raw headroom; estimated noninactive memory 99.1%; cgroup `max` cumulative 1531, `oom`/`oom_kill` both zero. Anonymous 2,069,741,568 bytes; file-backed 2,180,014,080 bytes; active_file 2,173,370,368 bytes; inactive_file 6,643,712 bytes. Web worker PID 57 RSS 1,210,740 KiB; scanner runs separately. The cgroup max counter cannot establish when all events occurred without historical same-cgroup samples; no proven leak.

## Immediate operator mitigation (not performed by this package)

1. Temporarily increase Render service memory/capacity, ideally from 4 GiB to at least 8 GiB if supported and economically acceptable, to restore headroom. Inspect Render memory and restart graphs before and after the change.
2. Confirm the deployed Start Command actually invokes `start_render.sh`. If Render uses an override (e.g., direct Gunicorn), this patch has no effect. Do not assume it is active merely because the repository contains it.
3. If immediate service degradation persists and capacity cannot be increased, preserve logs/evidence and use a controlled Render restart. This clears process-local diagnostic history, does not fix the root cause, and might delay scanning.
4. Never remove SQLite DBs, WAL/SHM files, evidence, or call `/proc/sys/vm/drop_caches` to address pressure. Avoid enabling trading authority.

## Implemented, low-risk bounded mitigation

One-line Gunicorn command in `start_render.sh` now uses `--max-requests 80 --max-requests-jitter 20 --graceful-timeout 120` with the existing `--workers 1 --threads 4 --timeout 120`. Gunicorn gracefully replaces web workers after 80–100 HTTP requests, limiting worker lifetime and long-lived web-process allocations without intentionally restarting the scanner or changing trading/settlement logic. The Gunicorn master remains the supervised web process. This is **not** a guarantee of reduced cgroup file cache or an observed memory leak fix. Worker recycling may cause transient CPU/memory spikes, latency, lost in-process caches or in-flight background tasks; verify application lifecycle safety and monitor in production. The request count does not impose a time-based or memory-based limit and requires traffic to trigger a recycle.

No new environment variables, endpoints, deletion, GC, database operations, application imports, scanner controls or release version changes. This is a **candidate**, not deployed.

## Validation

- `bash -n start_render.sh`: passed via tests.
- 31 containment + scanner supervisor tests passed.
- 73 selected tests passed, one Flask-dependent test deselected; includes configuration governance, original memory attribution, previous health/phase investigations, consolidation.
- 27 gamma transition and release truth tests passed.
- Full repository pytest collection blocked because this environment does not have `flask` installed. Re-run CI `smoke` and `tests` jobs using `requirements.txt` before deployment. No production certification claimed.

## Evidence to confirm mitigation

- Gunicorn master logs show graceful worker restart after ~80–100 completed requests; scanner PID/bootstrap stays continuous.
- Record before/after individual web worker RSS and cgroup anon/file, not just cgroup raw usage.
- Track `memory.events.max` delta in same cgroup, OOM events and psi; goal is no further max-event increments, with robust headroom.
- Compare `scanner_settlement_phase_memory_attribution` records from matching process identity; do not conflate scanner PID and Gunicorn worker PID.
- Confirm `/health` status and app routes, no change in scanner coverage/settlement/TradersPost authority.
- If cgroup memory still approaches 4GiB despite worker rotation, capacity/active-file-cache and scanner allocations need targeted remediation. Rollback by reverting the `start_render.sh` command to its former Gunicorn invocation.

## Scope and source integrity

Baseline repository: `apex-engine-main(20261106-121700).zip` plus earlier memory and phase candidate source overlays for compatible selected tests. **Only** `start_render.sh` changes production runtime behavior in this candidate. Diff generated against the untouched November 6 baseline start script; reconcile with the actual current deployed version before applying. Existing release remains 69.10.47.
