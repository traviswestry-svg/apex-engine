# APEX 47.0.1–47.0.4 — Architecture Consolidation & Evidence Readiness

## 47.0.1 Release manifest and capability registry
- Canonical version: 47.0.4
- Machine-readable capability registry
- `/api/version` and `/api/release-manifest`
- Root `app.py` identified as canonical; `engine.app` quarantined in registry

## 47.0.2 Canonical decision snapshot
- One immutable decision contract for dashboard, narrative, learning, replay and grading
- Deterministic decision IDs and explicit learning eligibility
- `/api/decision-snapshot/latest`

## 47.0.3 Evidence readiness diagnostics
- Durable SQLite decision, feature, price and grading ledger
- Explicit pipeline states and exclusion reason counts
- `/api/evidence-readiness`
- Dashboard Evidence Readiness panel

## 47.0.4 Automatic outcome grader
- Bounded automatic grading of matured actionable decisions
- Directional result, MFE, MAE and forward-price evaluation
- Explicit exclusion reasons; no silent skips
- Successful grades are forwarded to APEX 46 adaptive learning in shadow mode
- `/api/outcome-grader/run` and `/api/outcome-grader/summary`

No execution, order placement, order modification or cancellation authority was added.
