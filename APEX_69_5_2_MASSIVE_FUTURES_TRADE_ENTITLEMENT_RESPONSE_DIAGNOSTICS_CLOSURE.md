# APEX 69.5.2 — Massive Futures Trade Entitlement & Response Diagnostics Closure

## Scope
Diagnostics and credential-routing closure only. No tick-momentum math, decision authority, execution authority, confidence weighting, or aggregate-bar fallback changes.

## Closure
- Adds secret-safe provider HTTP diagnostics for the production futures trades request.
- Classifies authentication, entitlement/forbidden, endpoint-not-found, rate-limit, provider-error, transport-error, and confirmed-access states.
- Persists only bounded diagnostic metadata: HTTP status, content type, response byte count/kind, provider error code/message, request host, credential source, and entitlement state.
- Never exposes API keys, query strings, request headers, or raw response bodies.
- Fixes a shared HTTP-helper defect that overwrote an explicitly supplied Massive `apiKey` with `POLYGON_API_KEY` on `polygon.io` compatibility hosts. Explicit caller credentials now win; the global Polygon key is fallback-only.

## Preserved guardrails
- Individual futures transactions remain required.
- Aggregate futures bars remain prohibited as tick evidence.
- Stale futures trades remain excluded from live momentum state.
- Tick momentum remains observational only with production effect `NONE` and no decision/execution authority.
