# APEX 50.6.5.2 — Anthropic Adaptive Fallback + LTPE Embedded Path Repair

## Scope

This hotfix repairs two independent Morning Readiness regressions without changing trading, risk, scoring, or broker behavior.

### Anthropic narrative
- Replaces the shared 12-second pool with independent attempt budgets.
- Attempt 1 uses bounded server-side web search (default 6s).
- Attempt 2 is narrative-only from APEX deterministic context (default 10s).
- Hard total cap defaults to 18s, preventing the former ~40s failure mode.
- Keeps one retry maximum and exponential backoff.
- Preserves `pause_turn` continuation semantics.
- Adds exact failure classification: READ_TIMEOUT, CONNECT_TIMEOUT, HTTP_429, HTTP_5XX, AUTH_ERROR, BUDGET_EXHAUSTED, etc.
- Circuit breaker counts at most one failure per completed Morning Brief generation.
- Narrative output is capped to a configurable 1800 tokens by default.

### LTPE embedded path
- Uses the exact in-memory Morning Brief payload as the canonical level universe before consulting archive state.
- Structural path rendering no longer hard-fails when the LTPE statistics store is temporarily unavailable.
- Store/statistics failures remain warnings and probabilities remain evidence-only.
- Existing `50.6.5_INSTITUTIONAL_LEVEL_PATH_INTELLIGENCE` identity remains backward compatible; a separate resilience version is exposed.

## Default environment controls
- `APEX_BRIEF_AI_ENRICHED_TIMEOUT_SECONDS=6`
- `APEX_BRIEF_AI_DEGRADED_TIMEOUT_SECONDS=10`
- `APEX_BRIEF_AI_TOTAL_BUDGET_SECONDS=18`
- `APEX_BRIEF_AI_MAX_TOKENS=1800`
- Existing retry/circuit environment controls remain supported.

## Safety
No changes to order placement, risk guards, signal generation, LTPE learning policy, or market calculations.
