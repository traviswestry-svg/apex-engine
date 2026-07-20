# APEX 25.4 — DEPLOYMENT

## Prerequisites
- APEX 25.0-25.3 deployed. The 25.4 app.py is cumulative through 25.4.

## Steps
1. Extract `APEX_25_4_DELTA.zip` into the repository root (paths preserved).
2. Set `APEX_DECISION_REVIEW_DB` to a path under your production data volume
   (optional; defaults to apex_decision_review.db).
3. To enable recommendation approvals, set `APEX_OPERATOR_TOKEN` to a strong
   secret. Leave it unset to keep approve/reject disabled (they return 503).
4. Restart the app / Gunicorn. Expect on boot:
   `APEX 25.4 Institutional Decision Review routes registered (10 canonical
   routes verified, advisory-only).`
5. Verify `GET /api/decision-review/status` -> `production_effect: "NONE"`.

## Approvals
Send approve/reject with header `X-APEX-Operator-Token: <APEX_OPERATOR_TOKEN>`.
Approval only advances the governance workflow and writes an audit entry; it
never changes weights, thresholds, confidence, or execution.

## Post-deploy checks
- `/api/decision-review/recent|best|worst` respond 200.
- `/api/decision-review/report/daily_decision_review` responds 200.
- No new scanner process; existing endpoints unaffected.
