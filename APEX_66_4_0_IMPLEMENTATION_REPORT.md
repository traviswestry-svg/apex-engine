# APEX 66.4.0 — Canonical Decision Execution Governance

## What this build does
Makes the institutional reasoning layer **govern new risk initiation**. The
canonical decision's `NO_TRADE` now actually means *no new trade*: opening or
increasing risk fails closed unless the canonical Institutional Decision Object
is authoritative, actionable, thesis `ACTIVE`, direction-agreeing, and fresh.

The rule is **asymmetric and enforced structurally**: only the two risk-opening
executors on the canonical boundary consult governance. Risk-reducing /
protective actions (`EXIT`, `TRIM_*`, `PROTECT_PROFIT`, `MOVE_STOP_BE`,
`CANCEL`) never reach the gate and can never be blocked by thesis state. An
`INVALIDATED` thesis cannot trap a position.

## Chain, after this build
`Evidence → Reasoning → Thesis Lifecycle → Canonical Decision → Phase 9
Governance Gate (open-risk only) → Phase 10 → Broker`

## Files
- **New** `engine/execution/canonical_governance.py` — pure, deterministic rule
  (`evaluate_open_risk`) + `governance_snapshot_from_decision`. No I/O, no clock
  beyond the injected `now_epoch`.
- `engine/execution/canonical_execution.py` — `execute_single_leg` and
  `execute_complex` enforce governance after the risk guard, before the
  irreversible broker call; management/change/cancel executors untouched.
  Governance snapshot captured at preview, enforced at placement, bound to the
  preview; staleness measured from the decision's own timestamp.
- `engine/execution/trade_routes.py` — entry/strategy previews capture the
  current canonical decision governance snapshot via a `decision_provider` hook.
- `app.py` — wires `decision_provider` to build the canonical decision from the
  warm institutional bus (`STATE["last_result"]`).
- `engine/configuration_governance.py` — registers the two new env vars.
- `engine/version.py` — `66.3.2 → 66.4.0`.
- **New** `tests/test_apex_66_4_0_execution_governance.py` — 20 tests.
- `tests/test_apex_65_7_integrity.py` — two idempotency tests scoped to
  governance-off (orthogonal concern).

## Explicit blocker codes
`CANONICAL_DECISION_UNAVAILABLE`, `CANONICAL_DECISION_NOT_ACTIONABLE`,
`THESIS_NOT_ACTIVE`, `DECISION_DIRECTION_MISMATCH`, `CANONICAL_DECISION_STALE`,
`CANONICAL_DECISION_NO_TRADE` — surfaced in the rejection payload
(`data.governance.codes`) rather than a generic failure.

## Config
- `APEX_EXECUTION_GOVERNANCE_ENABLED` (default `true`) — controlled-rollout
  escape hatch. Never weakens exits.
- `APEX_CANONICAL_DECISION_MAX_AGE_SECONDS` (default `180`) — open-risk
  freshness budget.

## Safety properties (verified by tests)
- Open risk blocked on: unavailable / not-actionable / thesis
  FORMING·WEAKENING·CONFLICTED·INVALIDATED·UNKNOWN / direction mismatch /
  stale / missing timestamp.
- **Risk reduction never blocked**: `execute_management_exit` accepts only
  `SELL_CLOSE` and has no governance parameter — ungovernable by construction.
- Fail-closed default: a preview with no decision cannot open new risk.
- Flag off → governance does not gate (rollout control).

## Verification
- New governance suite: 20 passed.
- Full suite: 1813 passed, 10 deselected (unchanged baseline), 0 failures.
- Boot: clean, 877 routes.
- Patch applies cleanly onto the 66.3.2 baseline.

## Rollout note
With governance on (default), opening a new position requires a fresh
authoritative decision. When the market is closed or no snapshot exists, new
entries are refused (`CANONICAL_DECISION_UNAVAILABLE`) — correct for 0DTE — while
exits remain fully available. For a staged rollout, deploy with
`APEX_EXECUTION_GOVERNANCE_ENABLED=false`, confirm the entry path populates a
governance snapshot in a live session, then flip it on.
