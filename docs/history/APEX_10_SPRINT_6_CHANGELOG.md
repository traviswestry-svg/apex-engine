# APEX 10 Sprint 6 — Phase 8 Dashboard Evolution

## Release summary

Sprint 6 exposes the intelligence built in Sprints 1–5 through a read-only Evidence & Trust dashboard. It does not duplicate strategy logic, alter trade direction, promote learning policies, or convert historical similarity into a signal.

## Added

- `engine/dashboard_evidence.py`
  - Composes chain quality, event regime, confidence attribution, latest frozen sample, historical similarity, and calibration status.
  - Preserves explicit guardrails in the response contract.
- `engine/dashboard_evidence_routes.py`
  - Adds `GET /api/apex10/evidence?ticker=SPX`.
  - Recovers safely when historical stores are unavailable.
- Mission Control **Evidence & Trust** panel with:
  - Chain-quality ALLOW/CAP/SUPPRESS badge
  - Intraday event-regime badge
  - Effective and calibrated confidence
  - Component-level confidence attribution
  - Top leakage-safe historical matches
  - Matched-sample evidence note
  - Evaluation sample count, Brier score, calibration error, and promoted-policy status
  - Permanent similarity/learning guardrail notice

## Architecture guarantees

- Dashboard is read-only.
- Dashboard does not recompute direction.
- Historical similarity remains evidence, not a trade signal.
- Learning remains inactive unless a policy is explicitly promoted.
- Missing or insufficient evidence is displayed as unavailable rather than fabricated.
- Existing backend engines remain the source of truth.

## Files changed

- `app.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`
- `static/css/apex_os.css`

## Files added

- `engine/dashboard_evidence.py`
- `engine/dashboard_evidence_routes.py`
- `tests/test_dashboard_evidence.py`
- `APEX_10_SPRINT_6_CHANGELOG.md`

## Validation

- `587 passed`
- `0 failed`
