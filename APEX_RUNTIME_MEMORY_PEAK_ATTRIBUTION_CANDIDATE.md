# APEX Runtime Memory Stabilization & Peak Attribution Closure — Candidate

Scope: additive observation-only telemetry on the existing 69.10.37 baseline; no release-number bump. No automatic restarts, throttling, GC, cache eviction, database schema changes, or trading controls.

## Evidence motivating this patch

Render: 2 GB RAM / 1 CPU; OOM restart notification. `SCAN_WORKERS=1`. Scanner private dirty ~795 MiB in final six-minute sample, with a plateau; no proven leak. Gunicorn master/worker share substantial pages. CPU and memory pressure coexist. A full stage-specific cause is not established.

## Implementation

- `engine/runtime_memory_attribution.py`: read-only cgroup v2 memory.current, memory.max, memory.peak, memory.events, and Linux /proc PID smaps_rollup; JSONL records with bounded rotation; warning at 80%, critical at 92% (observational only).
- `start_render.sh`: lightweight monitor sidecar after scanner/Gunicorn start, killed on shutdown; configurable `APEX_MEMORY_MONITOR_ENABLED`, `APEX_MEMORY_SAMPLE_SECONDS`, `APEX_MEMORY_TELEMETRY_PATH`.
- `scanner_worker.py`: stage checkpoints around bootstrap, evidence grade, settlement, tick feed and heartbeat cycle; configurable `APEX_MEMORY_STAGE_ENABLED`, `APEX_MEMORY_STAGE_PATH`.
- `tests/test_runtime_memory_attribution.py`: three focused tests.

## Production readback (after deployment)

```
tail -n 5 /data/apex_runtime_memory.jsonl
tail -n 15 /data/apex_runtime_memory_stages.jsonl
```

Review memory cgroup usage and OOM counters alongside scanner completion and evidence capture. This patch does **not** directly instrument the `app.py` background scanner's individual scan, flow, feature and excursion stages; those remain a follow-up if the cgroup and scanner-worker checkpoint timeline does not isolate the peak. The monitor samples every 15 seconds and can miss shorter peaks; cgroup `memory.peak` helps identify such peaks where available. No assumption that OOM is fixed until sustained production validation.

## Release governance

The uploaded repo manifest is 69.10.37 and includes another 69.10.38 candidate. Keep this patch independently reviewable; merge and test before assigning a final release version. No deployment performed.
