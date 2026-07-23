# APEX Trade Director Phase 24 — Institutional Policy Governance Laboratory

Phase 24 converts Phase 22 learning and Phase 23 replay findings into evidence-gated policy proposals.

## Capabilities
- Policy proposals targeted to Phases 14, 19, 20, and 21
- Minimum-sample governance gates
- Confidence-calibration recommendations
- Strategy eligibility and priority recommendations
- Entry and exit-management shadow experiments
- Human approval, shadow validation, and rollback requirements

## Safety
Phase 24 is advisory only. It does not mutate configuration, risk limits, authorization thresholds, lifecycle behavior, or broker execution. No proposal can auto-apply.

## API
- `GET /api/position/policy-governance`
- `POST /api/position/policy-governance` with `action: EVALUATE_PROPOSAL`
