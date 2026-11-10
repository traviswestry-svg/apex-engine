# APEX Health Response Memory & Serialization Attribution — candidate

**Base:** November 6 repository `apex-engine-main(20261106-121700).zip`, with **prior APEX Runtime Memory Attribution Investigation candidate already integrated**. Production release remains **69.10.47**. This is a read-only observability change, **not production certified**.

## Scope
- Adds `engine/health_response_memory_attribution.py`, a bounded process-local eight-event ring buffer recording scalar metrics only.
- Instruments existing `app.py::health` payload construction and single `jsonify(_health_payload)` serialization. It does **not** call a second `json.dumps`, retain complete payloads, read databases, run GC, activate tracemalloc, modify scan scheduling, settlement, scores, order routing or trade decisions.
- Adds `/health` field `health_response_memory_attribution` containing a summary of the **most recent completed request**, not this request: the current request cannot include its finished serialization measurement in its own response without a second encoding pass. `completed_requests_observed` is capped at 8, and resets on web process restart.

## Fields and interpretation
`health_response_memory_attribution.last_completed` has `pid`, `payload_construction_ms`, `jsonify_serialization_ms`, `total_measured_ms`, `response_bytes`, `rss_before_kib`, `rss_after_construction_kib`, `rss_after_jsonify_kib`, `construction_rss_delta_kib`, `serialization_rss_delta_kib`, `total_rss_delta_kib`.

A high `serialization_rss_delta_kib` plus large `response_bytes` suggests short-lived response-buffer allocation. It **does not prove retention**. RSS changes can reflect concurrent requests/threads; the current response is still allocated when the post-jsonify RSS sample occurs. No automatic causality claims are made.

## Acceptance checks after integration
1. Run the repository's configured GitHub CI with complete runtime requirements. Do not deploy if smoke and mandatory test job fail.
2. Inspect `https://apex-engine-dashboard.onrender.com/health` twice. First response may show `NO_PRIOR_COMPLETED_REQUEST`; the second should show the first request's completed metrics. Do not compare fields across PID changes.
3. Compare response bytes and construction versus serialization RSS deltas across 3–5 requests without rapid polling; confirm whether high RSS persists after the request. Compare with separately collected `runtime_memory_investigation.web_process.rss_kib` and cgroup anon deltas at later times.
4. Monitor OOM/max/PSI counters and scanner completion; no automatic cleanup or increased trading authority.

## Validation performed locally
- Selected tests: **66 passed** (including new instrumentation, previous runtime memory module, consolidation, scanner, gamma transition/evidence, and settlement reconciliation).
- Python compilation passed.
- Full pytest invocation stopped during collection because Flask is not installed in this container (`ModuleNotFoundError: No module named 'flask'`). Accordingly the actual Flask `/health` route was not exercised as a running HTTP endpoint here; one static route-wiring test passed. Complete application CI/smoke still required.

## Integration
Apply `APEX_HEALTH_SERIALIZATION_INTEGRATION.patch` in the repository root with `patch -p1`, then add the `engine` and `tests` files from this ZIP. It is incremental **to the previously supplied runtime memory attribution candidate**; do not blindly apply to a differently updated `app.py`. Review diffs and resolve conflicts manually. No new environment variables, database schemas, routes or release version changes.
