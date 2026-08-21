# APEX 68.2 — Dynamic-State Alert Governance

## Scope
APEX 68.2 converts the 68.1 dynamic gamma/event state into deterministic alert-quality governance without creating a new directional engine.

## Changes
- Flow independence now propagates into normalized EngineOpinion objects and directly scales consensus evidence weight.
- Added `engine/dynamic_state_policy.py` to translate flow redundancy, residual pressure, gamma term divergence/fragility, gamma-path age, and event phase into transparent threshold/conviction/consensus adjustments.
- Institutional consensus now preserves raw effective consensus and additionally exposes `quality_adjusted_consensus` plus the dynamic-state policy object.
- Conviction consumes quality-adjusted consensus and applies the policy's conviction penalty while preserving fail-closed calibration behavior.
- Trade Director decision quality raises new-entry thresholds dynamically, suppresses new alerts during EVENT_IMMINENT/RELEASE, and makes PRICE_DISCOVERY WATCH_ONLY. Active position-management state is not suppressed by new-entry event gates.
- Dynamic State API now returns `alert_policy`.
- Dynamic State dashboard now displays Event / Alert Policy state, threshold adjustment, conviction penalty, and event timing.
- Dynamic-state surface now exposes canonical event phase alongside flow, residual pressure, gamma path, and gamma term structure.

## Governance
- No new directional signal is generated.
- Aligned residual pressure does not increase conviction; opposing residual pressure can reduce quality.
- Flow redundancy is weighted once at consensus and only receives a small decision-boundary buffer to avoid double-penalization.
- Event suppression applies to new alerts, not active position management.
- Existing 0DTE gamma, persistence, HLCE, and outcome stores remain authoritative.

## Validation
- 24 focused dynamic-state / gamma / event / mesh tests passed.
- 17 existing decision-reasoning / institutional-narrative / Trade Director decision-quality regression tests passed.
- All modified Python modules compile successfully.
