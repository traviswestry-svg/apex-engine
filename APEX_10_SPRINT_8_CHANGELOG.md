# APEX 10 Sprint 8 — Integration, Optimization, and Production Hardening

## Scope
Sprint 8 hardens the feature-complete APEX 10 institutional stack without changing trading direction, confidence logic, or strategy rules.

## Added
- `engine/production_observability.py`
  - Thread-safe, bounded in-memory latency samples.
  - P50, P95, maximum latency, call counts, error counts, and last-error metadata.
  - Explicit integration readiness assessment.
  - Read-only guardrails and fixed memory bounds.
- `engine/production_routes.py`
  - `GET /api/system/metrics`
  - `GET /api/system/readiness`
  - Readiness returns HTTP 503 when required APEX 10 capabilities are unavailable.
- Institutional-state request instrumentation
  - Counts institutional-state requests.
  - Measures canonical-state build latency.
  - Records build failures without swallowing exceptions.
- Application registration for production-readiness endpoints and capability checks.

## Integration capability checks
Readiness currently verifies availability of:
- Institutional state
- Dashboard evidence
- Decision provenance
- Learning and calibration
- Feature store

## Safety properties
- Observability is read-only.
- Metrics cannot change a trade decision.
- No automatic policy promotion.
- No historical evidence is converted into a live signal.
- Memory use is bounded to 512 samples per measured component.
- Missing critical capabilities are reported as degraded rather than hidden.

## Tests
Added:
- `tests/test_production_observability.py`
- `tests/test_sprint8_integration.py`

Validation result:

```text
599 passed
0 failed
```

## Release designation
This package is the production-hardened APEX 10 baseline and can be designated **APEX 10.1** after deployment-environment smoke testing and live paper-session validation.
