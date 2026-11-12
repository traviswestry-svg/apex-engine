# APEX 69.10.47 — First-stage memory-pressure mitigation (candidate)

## Scope
This is **not** a proven fix for cgroup memory-limit events. It addresses a concrete repeatable source of oversized operational messages: the scanner's ephemeral heartbeat carries historical settlement session reports and historical actionability decision samples, which are replicated into web `/health` responses.

On provided 2026-11-12 production snapshots, projecting scanner heartbeat diagnostics reduced serialized heartbeat size from **576,958 to 29,344 bytes** (~94.91%). This is not a memory-RSS reduction measurement.

## Changes
- Add `engine/heartbeat_payload_budget.py` (pure bounded diagnostic projection).
- Change `engine/operational_runtime.py::write_scanner_heartbeat` to apply the projection before serializing the heartbeat, fail-open.
- Preserve scanner heartbeat liveness, PID, startup identity, scanner coverage, and all key scheduler/settlement counts.
- Strip only large `last_result.session_reports`, `recent_decisions`, and `current_release_recent_decisions` from ephemeral heartbeat; their *counts* and omission markers remain.
- The original in-memory scheduler result and existing durable settlement reconciliation sidecar remain unchanged; no database edits, no retention changes.
- No new env vars. No memory reclamation, GC, VACUUM, WAL deletion, scanner timing changes or execution changes.

## Packaging and integration
Apply `APEX_HEARTBEAT_PAYLOAD_BUDGET.patch` to the **current deployed repository** (not blindly overwrite `operational_runtime.py`), then add `engine/heartbeat_payload_budget.py` and its test file. Reconcile with newer deployment changes before release. Does not include a full repository archive.

## Validation
- 33 selected tests passed, including heartbeat round-trip, consolidation, release-truth, gamma integrity, settlement eligibility, and settlement scheduler.
- `py_compile`: passed.
- Full suite: **not certified**; 68 collection errors due to missing environment dependencies (including Flask).
- 2026-11-12 observed heartbeat compression: 94.91%, on both supplied snapshots.

## Production acceptance checks
1. Verify heartbeat remains fresh and scanner coverage/settlement counts unchanged.
2. Verify `scanner_process.heartbeat_payload_budget.schema == "apex.heartbeat_payload_budget.v1"` and omission count fields are present.
3. Measure `/health` response size and health construction RSS deltas before/after deployment.
4. Independently sample `memory.events.max` **twice in same cgroup/worker** and compare counter delta; no expectation of automatic memory-limit event resolution.
5. Track web/scanner RSS, active_file, anon, and persistent storage. Avoid destructive database cleanup.

## Deployment limitation
Existing consumers of the heartbeat may expect detailed session reports or decision sample arrays; review their usage in the updated production repo. The archival data is not removed, but the ephemeral heartbeat no longer exposes those arrays. 
