# APEX 69.10.47 — Institutional OS Volume-Profile Single-Flight Memory Fix

## Classification
Incremental candidate against `apex-engine-main(20261114-103859).zip`; not deployed, not certified for production, no version or schema bump, no broker execution authorization.

## Source-supported root risk
`app.py::api_institutional_os()` created a new `ThreadPoolExecutor(max_workers=1)` for each composition's `_volume_profile_bundle` call. On `Future.result(timeout=_FETCH_TIMEOUT)`, `future.cancel()` does not stop an already-running callable; `shutdown(wait=False)` does not wait for it. A later composition could therefore create another executor while the earlier provider call is still running, causing overlapping volume-profile work and thread/temporary allocation pressure. The Nov 14 log confirmed a 3-second timeout and repeated `institutional_os` requests but does NOT establish this path as the sole source of the measured cgroup pressure.

## Correction
- Add process-local `engine/ios_volume_profile_singleflight.py` with one reusable worker and a nonblocking semaphore held **until the provider actually exits**, not until the caller's timeout.
- Report `BUSY` immediately with the same empty/default bundle as existing timeouts rather than queueing or launching a second volume-profile job.
- Preserve the original 3-second configured timeout, truthful `timed_out_components` classification, volume-profile input investigation, and downstream nine-engine composition/evidence rules.
- Expose bounded, scalar-only `/health.ios_volume_profile_singleflight` counters, no retained result payloads.
- Leave `start_render.sh` Gunicorn `--max-requests 80 --max-requests-jitter 20` unchanged. Gunicorn request-based worker recycling can be observed from the existing server logs; no new signal or execution authority.

## Limitations / remaining risks
- Timeout **cannot terminate** a provider stuck indefinitely. This implementation prevents overlapping work but a permanently blocked provider keeps the sole volume-profile slot busy; volume profile degrades until worker recycling or provider recovery. Underlying HTTP/file I/O still needs provider-specific timeouts.
- The **six-way base data fetch pool** still creates one executor per composition and may have similar timeout-tail risks. It was not changed to avoid broadening this patch; evaluate separately using observed evidence.
- This correction does not prove resolution of previous container memory events, and does not profile Python heap owners or prevent other application cache growth.
- Diagnostics are process-local; `/health` requests routed to different workers/instances have separate counters. Render has 2 instances; don't sum or infer same-instance trends across them.

## Verification
- `python -m compileall -q app.py engine/ios_volume_profile_singleflight.py tests/test_ios_volume_profile_singleflight.py`: passed.
- Selected pytest: 33 passed (`test_ios_volume_profile_singleflight.py`, SPXO compatibility, TradersPost paper dispatch, consolidation guard, release truth, gamma integrity).
- Full repository CI not run; Flask missing in this environment for app-level tests (`ModuleNotFoundError: flask`).
- Need full CI on GitHub/Render, particularly `tests/test_ios_single_flight.py` and institutional OS endpoint behavior, before deploying.

## Deployment acceptance
1. Reconcile patch against the current branch and run full CI.
2. Confirm unchanged execution hard stop and SPXO fail-closed invariants.
3. Verify 3-second provider timeout leads to single `timed_out` count, subsequent attempts while in-flight increment `busy_skips`; once provider completes, next request succeeds.
4. Compare same-instance `/health` private_dirty and cgroup anon before/after normal dashboard workload, and monitor `memory.events.max` and Gunicorn worker restarts.
5. Do not promote the cumulative research candidate or begin Stage 3 merely because this patch passes targeted tests.
