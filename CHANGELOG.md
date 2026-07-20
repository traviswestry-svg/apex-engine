# APEX 25.4 — Institutional Decision Review & Learning Engine (CHANGELOG)

Sprint 25.4 — the closed-loop review layer that completes the APEX 25.x shadow
trio (25.2 forecast / 25.3 calibration / 25.4 review). Advisory-only.
Built on the completed 25.3 delta (assumes 25.0-25.3 deployed).

## Added
- `engine/institutional_decision_review_v254.py` — deterministic review engine:
  * Full decision-lifecycle capture (evidence, health, thesis/counter, ranking,
    confidence waterfall, forecast, calibration layers, provider health, engine
    versions) assembled from the governed 25.0/25.1/25.2/25.3 stack.
  * Reproducible grading on DECISION QUALITY (not outcome direction) with an
    8-dimension decomposition (signal/evidence/reasoning/forecast/confidence/
    risk/timing/execution-readiness) and A+..F / NOT_GRADEABLE.
  * Error attribution (wrong direction, confidence over/understated, stale data,
    missing evidence, provider failure, invalidation/target sizing, correct-
    thesis-adverse-variance, favorable-outcome-weak-process, correct stand-down).
  * Governed learning recommendations (PROPOSED->UNDER_REVIEW->APPROVED/REJECTED
    ->DEPLOYED->ROLLED_BACK), each with supporting metrics, expected benefit,
    risks, and rollback plan. Nothing self-modifies.
  * Replay reconstruction from the stored snapshot only.
  * Eight institutional report builders.
- `engine/institutional_decision_review_v254_routes.py` — ten canonical routes
  plus a read-only report route. Approve/reject are operator-authorized.
- `tests/test_institutional_decision_review_v254.py` — 20 engine tests.
- `tests/test_institutional_decision_review_v254_routes.py` — 13 route tests.

## Modified
- `app.py` — fail-loud import + registration for 25.4 (mirrors 25.0-25.3).
- `engine/configuration_governance.py` — registered `APEX_DECISION_REVIEW_DB`
  and the safety-critical secret `APEX_OPERATOR_TOKEN`.

## Reuse (no duplication)
- Composes 25.0-25.3 for live review; writes the governance audit trail via
  `institutional_governance.audit` on approve/reject.

## Authorization
- Approve/reject use the repo's shared-secret idiom (`hmac.compare_digest`)
  against `APEX_OPERATOR_TOKEN`, supplied as `X-APEX-Operator-Token`. Unset ->
  503 (approvals disabled); wrong token -> 403. No production behavior changes on
  approval; only the governance workflow advances.
