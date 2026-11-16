# APEX 69.10.47 — Institutional OS Bounded Provider Execution & Web-Memory Containment

## Build result
**Candidate only; NOT deployed; Stage 3 deferred.** Built against 2026-11-14 source with the already deployed Institutional OS volume-profile single-flight candidate integrated as prerequisite. No release manifest bump, schema migration, trading/evidence/settlement changes, or execution-authority changes.

## Root cause and change
Institutional OS internal composition formerly instantiated a six-thread `ThreadPoolExecutor` for every refresh. Its shared 3-second timeout and `shutdown(wait=False, cancel_futures=True)` did not terminate already running HTTP/database calls. Sequential refreshes could leave previous provider tasks alive and create additional threads. This is a demonstrated concurrency-lifetime vulnerability; production memory savings are not yet measured.

The new `engine.ios_bounded_provider_execution` module uses one lazily utilized per-process `ThreadPoolExecutor(max_workers=6)` and a six-reservation, nonblocking concurrency gate. It submits **at most six** in-flight tasks and **never** maintains a pending backlog of unsent requests. A timed-out running task keeps its reservation until it really finishes. The provider key also rejects duplicate in-flight tasks. Busy, timeout and error paths return existing fallback values and appear in `timed_out_components`/partial reporting rather than being treated as fresh market data. Separate existing volume-profile single-flight remains untouched.

The existing Institutional OS response cache, TTL/freshness behavior and headless refresh design are preserved. No new independent provider-results cache is introduced, avoiding inadvertent staleness, and no provider data is retained in module-global state. Existing Gunicorn recycling, scanner, canonical gamma/evidence, broker preflight and dispatch remain unchanged. The pool limits a **single process**, not all Render instances combined. Provider timeout at the transport layer is still important: a forever blocked call can occupy a slot indefinitely, but it cannot create an unbounded queue.

## Operational verification
`/health.ios_bounded_provider_execution` returns process-local counts: `attempts`, `submitted`, `completed`, `timed_out`, `busy_skips`, `provider_errors`, `active`, `peak_active`, `maximum_active_calls=6`, `pending_queue_limit=0`. No result objects/quotes are retained for diagnostics. Counter reset on web worker recycling is expected.

Compare same-process RSS, private dirty, allocated blocks, cgroup `memory.events.max` and PSI under representative dashboard requests. `peak_active<=6`; `active<=6`; timeout count may rise without implying an overlapping task. Monitor degraded labels and whether provider tasks eventually complete.

## Validation
- 9 new/existing IOS concurrency tests passed.
- 51 selected tests passed against integrated November 14 tree, including SPXO, TradersPost, lifecycle, consolidation, release-truth and gamma integrity.
- Python compilation passed.
- Full repository CI was not run, and production memory improvement is not proven.

## Integration
**Preferred when previous volume-profile single-flight fix is already deployed:** apply `app.patch` with `git apply --check app.patch && git apply app.patch`, and add `engine/ios_bounded_provider_execution.py` and `tests/test_ios_bounded_provider_execution.py` from this package. Review patch against actual deployed commit, not only release number. If current app differs, reconcile manually; never overwrite a newer production app.py with the bundled reference snapshot. `app.py` is included as a review reference.

No additional environment variables required. Keep execution hard stop; do not enable paper/live routing by interpreting this infrastructure patch as certification.
