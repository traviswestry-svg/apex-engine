# APEX 13.0 Sprint 3 — Historical Readiness & Coverage

## Scope
Implemented a deterministic, read-only historical readiness layer over the existing Recommendation Ledger, immutable evidence packages, Sprint 2 quality assessments, and real graded outcomes.

## Capabilities
- Collected, graded, pending, eligible, excluded, and missing-evidence counters.
- Coverage by strategy, regime, session, weekday, and ticker.
- Date-span coverage and configurable minimum-history thresholds.
- Exclusion-rate and quality eligibility gates.
- Explicit `COLLECTING`, `INSUFFICIENT_HISTORY`, `DEGRADED_HISTORY`, and `READY_FOR_CALIBRATION` states.
- Feature-unlock reporting for calibration, similarity outcomes, strategy research, and adaptive candidate creation.
- Permanent prohibition on automatic production changes.
- Historical Readiness dashboard and read-only APIs.

## Safety
No recommendation outcome, performance statistic, calibration result, or missing field is inferred. Pending recommendations remain pending. The report uses persisted records only and does not query market-data providers.
