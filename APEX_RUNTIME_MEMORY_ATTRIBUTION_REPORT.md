# APEX Runtime Memory Attribution — focused investigation candidate

**Baseline:** APEX 69.10.47 research and operations snapshot; source `apex-engine-main(20261106-121700).zip` with previous exact-identity/volume-auction observability candidate applied in a staging copy. **Status:** candidate, not deployed, not release-certified. No release manifest bump.

## Motivation: November 9 at 20:14 ET

- Cgroup memory.current = 4,278,312,960 / 4,294,967,296 bytes (99.61%).
- cgroup inactive_file = 249,176,064 bytes; estimated non-inactive usage = 4,029,136,896 bytes (93.81%).
- memory.events `max` = 696 **cumulative**; `oom=0`, `oom_kill=0`; PSI avg10 = 0.0.
- Scanner journal 539 completions / 539 attempts, zero failures; disk passes at 27.77% free.
- These readings establish severe headroom loss, **not** a proven application leak, SQLite leak, or continuous memory events.

## Changes

1. New `engine/runtime_memory_investigation.py` exposes compact read-only **cgroup v2 memory attribution** via `/health` at `runtime_memory_investigation`. It reads a fixed set of values from memory.current, memory.max, memory.peak, memory.stat, and memory.events and `/proc/self/status`. Records anonymous bytes, file bytes, inactive/active file, shared, slab, kernel, socket, and web-process RSS. It explicitly notes that cgroup breakdown classes overlap and must not be summed.
2. Bounded process-local trend (max 12 readings, no more often than every 30 seconds). Shows changes in anonymous memory, file memory, total cgroup usage, web RSS, and delta of cumulative `max`/OOM counters. No history continuity is claimed across process restarts. State `MEMORY_LIMIT_EVENTS_INCREASING` is observational only.
3. Existing `engine/runtime_memory_attribution.py` sidecar extends its periodic cgroup samples with selective memory.stat keys. Existing `engine.paired_runtime_diagnostics` already captures process RSS/PSS/private dirty before/after `FULL_SCAN`, `EVIDENCE_GRADE`, `SETTLEMENT_PASS`, `TICK_FEED_PASS`, and `HEARTBEAT_CYCLE` into bounded JSONL. This patch does **not** add new provider calls, scan jobs, or database queries.
4. Existing release and governance flags, scanner authority, settlement eligibility, trade decision logic, SQLite settings, and disk-cleanup policy remain unchanged. No new environment variables and no unbounded allocations. The endpoint explicitly disclaims precise SQLite heap attribution; determining per-connection cache usage would need a separate scoped design.

## Readback

- `https://apex-engine-dashboard.onrender.com/health` (not `/api/status`) → `runtime_memory_investigation`
- `https://apex-engine-dashboard.onrender.com/health` → existing `memory_pressure`
- On service shell if already available, read latest bounded sidecar records: `tail -n 5 /data/apex_runtime_memory.jsonl` and `tail -n 10 /data/apex_runtime_memory_pairs.jsonl` (paths depend on existing deployment configuration). Do **not** expose these file paths as new HTTP endpoints or open the large databases merely to observe memory.
- Compare at least several snapshots spanning scanner and settlement cycles. Verify `max_events_since_first_sample` increases, anon/file trends, and web/worker process RSS via paired records before concluding a cause.

## Release truth and tests

- `pytest` selected battery: **62 passed, 1 deselected**. Includes novel attribution tests, existing monitor tests, paired runtime, pressure classification, settlement/auction diagnostics, gamma transition, gamma integrity, consolidation guard, configuration-governance tests (excluding Flask endpoint test), and release-truth tests.
- Full `pytest -q --maxfail=1` stopped during collection: `ModuleNotFoundError: No module named 'flask'` from institutional decision integrity. One selected configuration endpoint test also failed for that same missing dependency. Hence full CI and Flask `/health` integration tests are **not passed** here.
- `compileall` passed for app.py and both changed runtime modules.
- **Deployment hold:** Run configured CI with `pip install -r requirements.txt pytest`, verify health route output, confirm no diagnostic work changes trading decisions, and review stability over multiple production cycles.

## Packaging/integration notes

ZIP contains a `.patch` for the two modified existing files instead of dropping a potentially stale full `app.py` over newer production work. It also includes the new module and tests. Apply to a current branch with `git apply --check` (or manually reconcile the two app.py additions if branch drift exists), then `git apply`. Because the patch is based on an app.py that already includes the immediately prior settlement/volume-auction investigation candidate, apply only the new runtime changes when rebasing onto a newer branch.
