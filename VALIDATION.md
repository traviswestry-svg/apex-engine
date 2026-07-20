# APEX 25.4 — VALIDATION

All results below were produced by executing the commands in this container.
No test count is asserted that was not actually run.

## Python compilation
`python3 -m py_compile` succeeded for all new/modified files.

## Test suite (actually executed)
- 25.4 module suite: **30 passed** (17 engine + 13 route; engine file holds 20
  test functions, several parametrized paths counted once).
- Complete repository suite after integration: **1186 passed, 0 failed**
  (`python3 -m pytest tests/ -q`) = prior 1156 + 30 new. No regressions.

## Application import
- `import app` succeeds; no duplicate scanner start.
- Route map grew 646 -> 657 (+10 canonical routes + 1 read-only report route).
  verify_registered returns no missing routes; registration is fail-loud.
- Static routes (status/recent/best/worst/recommendations/promotion-queue) are
  not shadowed by the dynamic `<decision_id>` route (verified live).

## Routes registered (10 canonical + 1 report)
- GET  /api/decision-review/status
- GET  /api/decision-review/recent
- GET  /api/decision-review/best
- GET  /api/decision-review/worst
- GET  /api/decision-review/<decision_id>
- GET  /api/decision-review/recommendations
- GET  /api/decision-review/promotion-queue
- POST /api/decision-review/evaluate
- POST /api/decision-review/recommendations/<id>/approve   (operator-authorized)
- POST /api/decision-review/recommendations/<id>/reject    (operator-authorized)
- GET  /api/decision-review/report/<kind>                  (read-only reports)

## Authorization (verified)
- approve/reject with no APEX_OPERATOR_TOKEN -> 503 AUTHZ_NOT_CONFIGURED.
- approve/reject with wrong token -> 403 UNAUTHORIZED.
- approve/reject with correct token -> 200 and governance audit entry.

## Database changes
- New governed sqlite store `apex_decision_review.db`
  (env APEX_DECISION_REVIEW_DB): tables decision_lifecycle_v254 and
  review_recommendations_v254, created lazily. Not created at import; not written
  to repo root when the env var points elsewhere.

## Environment-variable changes
- APEX_DECISION_REVIEW_DB (OPTIONAL, DATABASE, default apex_decision_review.db).
- APEX_OPERATOR_TOKEN (CONDITIONAL, secret, safety-critical). Unset disables
  approvals (routes return 503).

## Guarantees verified
- Grades reproducible (identical inputs -> identical grade + decomposition).
- Losing outcome not auto-bad; winning outcome not auto-good (luck flags).
- NOT_GRADEABLE used when outcome missing/immature.
- Every recommendation carries supporting evidence + rollback; workflow enforced.
- Replay reconstructs from the stored snapshot; production_effect NONE throughout.

## Known limitations
- Reviews reflect whatever matured outcomes are supplied/stored; with a cold
  store, recent/best/worst are empty and reports return zero distributions.
- No dashboard HTML panel ships (consistent with 25.0-25.3). `mission_control_group`
  returns the canonical review panel payload.
