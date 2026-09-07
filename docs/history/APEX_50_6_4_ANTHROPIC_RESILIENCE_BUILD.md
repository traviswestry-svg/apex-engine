# APEX 50.6.4 — Anthropic Integration Resilience

## Objective
Make Anthropic an optional narrative enhancement rather than a latency dependency for the Morning Brief.

## Changes
- One controlled retry only: maximum two Anthropic attempts per Morning Brief generation.
- Exponential backoff between attempts; default base delay is 0.75 seconds.
- Retry is limited to transient failures: request timeout, connection error, HTTP 408/409/429, HTTP 5xx, and empty upstream response.
- Authentication/client configuration failures such as HTTP 401/403 are not retried and do not count toward opening the circuit breaker.
- Circuit breaker opens after repeated retryable request failures (default threshold: 3 complete failed calls).
- While the circuit is open, APEX skips Anthropic network I/O and immediately uses the deterministic Morning Brief.
- After the cooldown (default 120 seconds), the next request becomes a half-open probe. Success closes/reset the circuit; retryable failure reopens it.
- Successful Anthropic responses reset consecutive failure count.
- Existing deterministic fallback remains authoritative and unchanged.

## Telemetry
Morning Brief output now includes `anthropic_telemetry`, containing:
- provider/model
- outcome (`SUCCESS`, `FAILED`, `CIRCUIT_OPEN`, `NO_KEY`)
- per-attempt duration
- HTTP status where available
- error type and bounded error description
- retryability decision
- backoff applied before retry
- retry count
- total Anthropic duration
- whether network I/O occurred
- circuit state, consecutive failures, threshold, cooldown, and last success/error metadata

`narrative_attempt` also exposes compact `attempt_count`, `retry_count`, and `circuit_state` fields for dashboard/operations use.

## Configuration
- `APEX_BRIEF_AI_TIMEOUT_SECONDS` — per-attempt timeout; default 10 seconds
- `APEX_BRIEF_AI_RETRY_BACKOFF_SECONDS` — exponential backoff base; default 0.75 seconds
- `APEX_BRIEF_AI_CIRCUIT_FAILURE_THRESHOLD` — failed-call threshold; default 3
- `APEX_BRIEF_AI_CIRCUIT_COOLDOWN_SECONDS` — open-circuit cooldown; default 120 seconds

The maximum attempt count is intentionally fixed at two (initial + one retry) to keep the integration bounded.

## Safety / behavior
- No trading, signal, risk, LTPE, market-data, or broker behavior changed.
- Anthropic remains optional.
- Circuit-open state never blocks deterministic Morning Brief generation.
- API keys are never emitted in telemetry.

## Validation
- Anthropic resilience tests: 4/4 PASS
- Morning Brief hotfix compatibility tests: 3/3 PASS
- Engine package Python compilation: PASS
- Failure injection covers retry-success, non-retryable auth error, breaker-open network bypass, and Morning Brief telemetry propagation.
