# APEX 65.1 — Frontend Runtime Stabilization & API Reliability

## Scope
Reliability-only frontend build. No signal, scoring, strategy, sizing, risk, or broker execution logic changed.

## Implemented
- Added `static/js/apex_api.js`, a shared frontend API client.
- Standardized request timeout, HTTP/JSON error handling and cache-backed GET fallback.
- Reads backend `X-APEX-Request-ID` and `X-APEX-Duration-Ms` correlation headers.
- Emits `apex:api-result` events and maintains a runtime request-health snapshot.
- Standardized frontend runtime states: HEALTHY, DEGRADED, STALE, UNAVAILABLE, DISABLED, FAILED.
- Migrated the Trade Director's 24-request refresh fan-out to the shared API client.
- Added visible Trade Director API state, failed/degraded count and most recent request ID.
- Loaded the shared client ahead of the Institutional OS runtime to support staged migration of remaining calls.
- Preserved fail-soft dashboard behavior; failed GETs use a last-known-good in-memory response when available.

## Safety
POST execution paths were not automatically retried and no broker/order semantics were changed.
