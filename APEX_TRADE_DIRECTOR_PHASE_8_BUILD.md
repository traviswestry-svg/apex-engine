# APEX Trade Director Phase 8 — Real-Time Management Policy Engine

## Added
- Regime classification: trend continuation, balanced auction, conflicted, exhaustion risk, or data-limited.
- Stable management policy that combines the core recommendation with Phase 7's adaptive second opinion.
- Immediate escalation to more defensive actions when safety guards trigger.
- Three-cycle confirmation before a less-defensive de-escalation is shown.
- Confirmation gates: Monitor, Prepare Action, User Confirmation Required, and Immediate Protection.
- User acknowledgement and override audit trail.
- New endpoints: `GET /api/position/policy` and `POST /api/position/policy/decision`.

## Safety and stability
- No broker order is sent or modified.
- No provider request, scanner, background thread, timer, startup database connection, or import-time workload was added.
- Policy state lives inside the already active manual position.
- Overrides are recorded for replay and future calibration but do not execute.
