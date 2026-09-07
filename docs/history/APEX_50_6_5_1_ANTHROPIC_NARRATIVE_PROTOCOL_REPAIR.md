# APEX 50.6.5.1 — Anthropic Narrative Protocol Repair

## Objective
Restore reliable Morning Brief AI narrative generation without making Anthropic a blocking dependency.

## Root Cause
The APEX Anthropic integration supported server-side web search but did not handle the Messages API `pause_turn` protocol. A 200 response containing `stop_reason: pause_turn` and server-tool content could therefore be treated as an empty narrative and the whole request retried from scratch. This was especially harmful under a hard latency budget.

## Repairs
- Handle `stop_reason: pause_turn` as a protocol continuation.
- Send the returned assistant content back to Anthropic with the same server-side web-search tool, bounded by a continuation limit.
- Bound web search to a configurable maximum use count (default 1).
- Keep one controlled transient retry maximum.
- On a transient enriched/web-search failure, retry narrative generation without web search so APEX can still obtain a narrative from deterministic market context.
- Preserve the total Anthropic wall-clock budget and circuit breaker.
- Distinguish `BUDGET_EXHAUSTED`, `CIRCUIT_OPEN`, timeout, HTTP/configuration error, and successful narrative outcomes.
- Expose protocol telemetry directly in Morning Readiness: attempt count, API-call count, pause-turn continuation count, total AI time, circuit state, and degraded no-web retry state.
- Add `anthropic_integration_version = 50.6.5.1_ANTHROPIC_NARRATIVE_PROTOCOL` to the Morning Brief payload.

## Safety / Non-Changes
- Deterministic Morning Brief remains authoritative for levels and numbers.
- No trading, scoring, LTPE probability, risk, order, or broker behavior changed.
- No API key, prompt body, response body, or web-search result body is exposed in telemetry.
- Evidence-only LTPE behavior remains unchanged.

## Validation
- 86/86 APEX 50.6 + APEX 65 stabilization tests PASS.
- New `pause_turn` continuation regression PASS.
- Transient retry-without-web-search regression PASS.
- Budget-exhaustion status regression PASS.
- Dashboard inline JavaScript syntax PASS after Jinja substitution.
- Python compilation PASS.
