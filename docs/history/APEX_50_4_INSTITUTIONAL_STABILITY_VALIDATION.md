# APEX 50.4 — Institutional Stability & Validation

Adds production diagnostics for Morning Brief generation without changing trade logic.

## New endpoint
`GET /api/morning-brief/validation`

Reports total generation duration, provider status/latency, cache state, section presence, data-quality score, fallback count, missing-field count, warnings, and exceptions. Failed Morning Brief generations are recorded rather than disappearing behind a generic HTTP 500.

## Deployment validation
1. Deploy changed files.
2. Request `/api/morning-brief?refresh=1`.
3. Open `/api/morning-brief/validation`.
4. Confirm status is `HEALTHY` or review explicit `DEGRADED` warnings/provider errors.
