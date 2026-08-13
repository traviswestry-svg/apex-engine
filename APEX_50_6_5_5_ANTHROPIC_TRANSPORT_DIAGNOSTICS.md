# APEX 50.6.5.5 — Anthropic Transport Diagnostics & Payload Optimization

## Objective
Isolate and reduce the remaining Anthropic `READ_TIMEOUT` failures without changing the deterministic Morning Brief, LTPE, trading, risk, or broker paths.

## Findings
The async architecture introduced in 50.6.5.3/50.6.5.4 removed Anthropic from the synchronous Morning Readiness path, but the background worker still inherited aggressive transport limits intended for synchronous UX: roughly 6 seconds for the enriched request and 10 seconds for the narrative-only fallback. The production telemetry showed both calls reaching those read deadlines. Once Anthropic is asynchronous, those short deadlines no longer provide a user-latency benefit and can manufacture avoidable `READ_TIMEOUT` failures.

## Changes
- Anthropic integration version advanced to `50.6.5.5_ANTHROPIC_TRANSPORT_DIAGNOSTICS`.
- Added separate short connect timeout (`APEX_BRIEF_AI_CONNECT_TIMEOUT_SECONDS`, default 4s).
- Raised async enriched read budget to 22s by default.
- Raised async no-web fallback read budget to 28s by default.
- Raised total background narrative budget to 55s by default; this does not block Morning Readiness.
- Reduced normal narrative output cap default from 1800 to 1400 tokens.
- Added degraded fallback output cap (`APEX_BRIEF_AI_DEGRADED_MAX_TOKENS`, default 950).
- Degraded retry removes web-search instructions and reduces requested narrative length from ~700 words to ~350 words.
- Added request-level telemetry: endpoint host/path, payload bytes, prompt chars, approximate input tokens, connect timeout, read timeout, max output tokens, request duration, HTTP status, Anthropic request ID when available, and exact exception/failure type.
- Mobile Morning Readiness async narrative telemetry now shows exact failure class plus payload KB and read-timeout budget.

## Safety / Scope
- Anthropic remains asynchronous and cannot delay the deterministic Morning Brief response.
- Deterministic levels, LTPE probabilities, trading, risk, scoring, execution, and broker logic are unchanged.
- API key values are never included in telemetry.

## Validation
- 97/97 APEX 50.6 + APEX 65.x regression tests PASS.
- Repository Python compilation PASS.
- New transport tests cover realistic separate read budgets, payload/request-ID telemetry, exact READ_TIMEOUT recording, and degraded prompt compression.
