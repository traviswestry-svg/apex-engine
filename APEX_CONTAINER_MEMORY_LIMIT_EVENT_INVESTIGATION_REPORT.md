# APEX Container Memory-Limit Event Investigation — Candidate

**Baseline:** APEX 69.10.47, Nov 6 source archive overlaid with prior four memory candidates in order: Runtime Memory Attribution, Health Response Memory & Serialization Attribution, Scanner/Settlement Phase Memory Attribution, Phase-Record Writer/Reader Reconciliation.

## Production question

Nov 12 `/health` reported cumulative `memory.events.max=27`, `memory.events.oom=0`, `memory.events.oom_kill=0`, and `memory.peak=4,294,967,296` bytes (the 4-GiB limit). This establishes the memory limit was reached in the cgroup lifetime, **not when**, whether the 27 events were recent, or which process caused them.

## Change

- New `engine/container_memory_limit_event_investigation.py` samples **cgroup v2** `memory.events`, `memory.current`, `memory.peak`, `memory.max`, `memory.stat` (anon/file/active/inactive), and `memory.pressure` PSI avg10.
- New `/health` field `container_memory_limit_event_investigation`, with initial status `BASELINE_ESTABLISHED_NO_EVENT_TIME_INFERRED`, subsequent `NO_NEW_MAX_EVENTS` or `NEW_MAX_EVENTS_OBSERVED`.
- Event counter deltas are only compared under the same verified boot-ID + cgroup filesystem device/inode identity and monotonic sample order. Reset, PID-independent cgroup replacement, or clock reversal resets the baseline.
- When a new `max` event occurs, a bounded interval records **start/end timestamps**, counter deltas (including OOM and kills), anon/file/active/inactive changes, PSI, and sampled memory peak/current. It reports phase context only for the **last verified scanner/settlement completion** in each stage/process as summarized by the existing bounded reader. Never attributes an allocation to a phase based on timing alone.
- Bounded worker-local storage: at most 16 samples and 8 event intervals. No DB queries, file writes, cgroup writes, forced GC, process scanning, or execution authority.
- No new environment variables or configuration registry changes.

## Safety and limitations

1. The preexisting 27 `max` events form a baseline; they cannot be assigned to individual phases or timestamps.
2. `/health` sampling only brackets events between HTTP calls; if one happens between calls the time bracket can be wide.
3. An event may arise in **any** process in the cgroup, not necessarily the web worker, scanner, or settlement process.
4. The phase correlation examines only the latest completion per stage/process from the preexisting 64-record bounded phase reader, and can miss activity within a bracket. This is not causal proof.
5. Worker-local history resets on restart; different web workers may report different baselines. Use process PID and identity to interpret samples.
6. The event `max` count is not an OOM-kill count. High raw usage with reclaimable cache alone does not establish unrecoverable pressure.

## Integration

Apply `APEX_CONTAINER_MEMORY_LIMIT_EVENT_INTEGRATION.patch` to the current deployed tree **after** the four preceding candidates; install the new `engine` module. The patch targets only `app.py`, does not change `/health` decision fields, and APEX release version remains 69.10.47.

## Local validation

- Focused instrumentation tests: **35 passed**.
- Wider selected suite: **63 passed**, including consolidation, release truth, gamma-integrity, settlement eligibility and scheduler closure.
- Python compilation: passed.
- Full suite attempted: **68 errors during test collection** due to unavailable Flask dependency; not full-CI certified.

## Production validation sequence

1. Confirm the new `/health` key and **baseline** status after deployment.
2. Inspect at least two subsequent responses **from the same `web_worker_pid`**, preferably spanning scanner/settlement activity.
3. If `max` counter increases, inspect `new_max_event_intervals[-1]` alongside anon/file deltas, OOM and PSI; compare with bounded phase-completion context, without inferring causation.
4. If max events stop but raw memory remains elevated, avoid conflating file-backed cache with proven retained heap growth.
5. Keep trading execution authority unchanged; separately certify paper order routing before any change to execution settings.
