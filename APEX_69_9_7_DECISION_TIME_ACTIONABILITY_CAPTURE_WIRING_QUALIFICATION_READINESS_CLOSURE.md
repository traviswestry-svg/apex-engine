# APEX 69.9.7 — Decision-Time Actionability Capture Wiring & Qualification Readiness Closure

## Purpose

69.9.7 closes the production wiring gap exposed by the first 69.9.6 live evidence.
The counterfactual qualification engine was fail-closed and correct, but new scanner
records still reported `actionability_window_source_present=false`,
`entry_cutoff_et=null`, and `cutoff_passed=null` even while other new decision-time
fields such as conviction, thesis state, and trade-guidance state were successfully
persisted.

This release is observational. It does not change the 11:30 cutoff, any blocker,
confidence, calibration, risk limit, order validation, execution authority, or broker
state.

## Root Cause

The canonical scanner evidence capture and Trade Director Phase 11 do not share the
same composition object at the historical-evidence capture point.

69.9.6 attempted to read:

`result.session_intelligence.session.{mode,cutoff,cutoff_passed}`

That source is valid on Trade Director surfaces, but it is not guaranteed to exist on
the scanner result when the canonical institutional decision is frozen. Therefore the
live scanner could persist `trade_guidance_enabled`, thesis state, and conviction from
the Institutional Decision Object while still missing the entry-window fields.

A second production-shape mismatch was also identified: scanner `recommendation` can
be a string, while 69.9.6 normalized only mapping-shaped recommendations. That caused
live recommendation action/state attribution to remain `UNKNOWN` even when a scanner
recommendation string existed.

## Decision-Time Entry Window Source

69.9.7 keeps Session Intelligence as the preferred source when it is genuinely
present. When it is absent, the evidence lifecycle reads the exact entry-window policy
from:

`engine.execution.trade_risk_guard.RiskLimits.no_new_trades_after_et`

This is the same contract already enforced by new-entry risk validation and is sourced
from `TRADE_NO_NEW_AFTER_ET` with the existing code default.

The new helper:

`entry_window_policy_snapshot(...)`

is pure and observational. It accepts the canonical decision timestamp and session
state and returns:

- `entry_cutoff_et`
- `cutoff_passed`
- `market_session_authorized`
- `entry_window_authorized`
- source module / policy / environment key

It does not approve an order or modify `RiskLimits`.

## Actionability Capture v2

New snapshots persist:

`apex.counterfactual_actionability_capture.v2`

with:

- `entry_window_source`
  - `SESSION_INTELLIGENCE`
  - `TRADE_RISK_GUARD_POLICY`
  - `UNAVAILABLE`
- `entry_window_source_present`
- `entry_cutoff_et`
- `cutoff_passed`
- `entry_window_authorized`
- `market_session_authorized_by_entry_policy`
- normalized recommendation action/state/source
- existing thesis/conviction/trade-guidance evidence
- field-level `capture_provenance`

## Field Provenance

Required actionability fields now report one of these capture states:

- `SOURCE_PRESENT`
- `DERIVED_FROM_DECISION_TIME_POLICY`
- `SOURCE_PRESENT_NULL`
- `SOURCE_PATH_NOT_FOUND`
- `SOURCE_ERROR`

Missing source values are never inferred.

`session_mode` remains missing when Phase 11 is not present. It is not fabricated from
the entry-risk policy. Counterfactual qualification no longer requires Phase 11 merely
to prove the cutoff when the actual new-entry risk policy was captured.

## Recommendation Shape Closure

`result.recommendation` is now captured whether it is:

- a mapping with `action` / `state`, or
- a non-empty scanner recommendation string.

No recommendation is synthesized when both sources are absent.

## Qualification Readiness

`counterfactual_regret` advances to:

`apex.counterfactual_regret_qualification.v2`

and now includes:

`actionability_capture_readiness`

with:

- total entry-window evidence coverage
- capture-version counts
- entry-window source counts
- per-field provenance-status counts
- current-release row count
- current-release entry-window evidence coverage
- `CURRENT_RELEASE_READY`, `CURRENT_RELEASE_PARTIAL`,
  `CURRENT_RELEASE_NOT_READY`, or `WAITING_FOR_CURRENT_RELEASE_LIVE_CAPTURE`

The Premium Discipline dashboard surfaces these readiness values directly.

## Historical Integrity

69.9.7 does not rewrite historical decisions.

Legacy records with no persisted actionability source remain fail-closed and continue
to report `ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE`.

The current runtime cutoff is still reference-only for legacy history and cannot be
used to retroactively qualify an old trade.

## Authority Boundaries

69.9.7 does not:

- alter `TRADE_NO_NEW_AFTER_ET`;
- alter `APEX_SESSION_CUTOFF`;
- change `THESIS_INVALIDATED` or any blocker;
- change canonical actionability;
- change confidence or consensus weights;
- activate calibration;
- submit, modify, or cancel an order;
- grant broker or execution authority.

## Production Verification Target

After deployment and one live 69.9.7 scanner cycle, `/api/triggers/counterfactual-regret`
should begin showing current-release records with:

- `capture_version: 69.9.7`
- `entry_window_source: TRADE_RISK_GUARD_POLICY` on scanner paths without Phase 11
- `entry_cutoff_et: 11:30` when that remains the configured risk policy
- non-null `cutoff_passed`
- `actionability_window_source_present: true`
- field-level capture provenance

`actionability_capture_readiness.current_release_entry_window_evidence_pct` is the
primary forward-validation metric.
