# APEX 69.9.6 — Actionability Window & Counterfactual Regret Qualification Closure

## Purpose
69.9.6 closes the final truth gap between a directionally correct blocked thesis and a genuinely trade-eligible missed opportunity.

69.9.5 proved that some blocked theses moved favorably inside the governed five-minute window. That was still insufficient to call them missed trades because historical actionability-window evidence, independent disqualifiers, and canonical recommendation-layer state were not fully qualified.

69.9.6 remains observational. It does not alter blockers, confidence, thresholds, consensus, calibration, execution authority, or broker state.

## Decision-Time Actionability Capture
`engine.historical_evidence_lifecycle.build_snapshot()` now persists a bounded `counterfactual_actionability` block after the canonical decision has completed.

Captured fields include:
- decision-time Session Intelligence presence;
- session mode;
- exact persisted entry cutoff;
- exact `cutoff_passed` state;
- market session;
- institutional narrative `trade_guidance_enabled`;
- thesis state;
- direction;
- conviction score;
- canonical conviction blocking conditions;
- IDO actionable/status;
- recommendation action/state;
- final canonical action;
- entry-reference availability;
- exact persisted target/decision-level object;
- dynamic-policy state and blocking conditions.

The capture is post-decision and observational only.

## Historical Truth Rule
Historical actionability is never reconstructed from today's runtime cutoff.

When older decisions do not contain persisted decision-time Session Intelligence/cutoff evidence, 69.9.6 reports:

`ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE`

The current `APEX_SESSION_CUTOFF` value is shown only as a reference diagnostic. It cannot convert an old observation into `OUTSIDE_ACTIONABILITY_WINDOW` or `COUNTERFACTUAL_TRADE_ELIGIBLE`.

## New API
`GET /api/triggers/counterfactual-regret?symbol=SPX`

The same block is embedded in:

`GET /api/triggers/predictive-validation?symbol=SPX`

Predictive validation advances to:

`apex.predictive_validation.v7`

Counterfactual qualification schema:

`apex.counterfactual_regret_qualification.v1`

## Qualification Contract
A blocker-specific observation can become counterfactually trade-eligible only when all required source evidence is present:

1. Canonical directional grade is correct.
2. Session is an entry-authorized regular-market session.
3. Exact decision-time actionability-window evidence is persisted.
4. The persisted cutoff had not passed.
5. Persisted Session Intelligence did not require `STOP_TRADING`.
6. Trade guidance was not disabled.
7. Direction was actionable.
8. Any non-active thesis-state gate is attributable only to the blocker being evaluated.
9. Any low-conviction gate is attributable only to the blocker being evaluated.
10. No independent trigger blocker or captured policy blocker remains.
11. Entry geometry exists.
12. A persisted explicit target or governed movement threshold exists.
13. A valid in-window five-minute excursion exists.

If the persisted threshold is reached after all gates pass, the row may be classified:

`POTENTIAL_BLOCKER_REGRET`

This remains counterfactual evidence only. It does not prove option premium, fill quality, stop viability, slippage, executable timing, or realized profitability.

## Qualification States / Reasons
The new surface distinguishes:
- `ABSTENTION_SUCCESS`
- `DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE`
- `COUNTERFACTUAL_TRADE_ELIGIBLE`
- `POTENTIAL_BLOCKER_REGRET`
- `NOT_CANONICALLY_GRADED`

Grounded reasons include:
- `SESSION_NOT_ENTRY_AUTHORIZED`
- `ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE`
- `OUTSIDE_ACTIONABILITY_WINDOW`
- `TRADE_GUIDANCE_DISABLED`
- `DIRECTION_NOT_ACTIONABLE`
- `INDEPENDENT_THESIS_STATE_DISQUALIFIER`
- `INDEPENDENT_CONVICTION_DISQUALIFIER`
- `INDEPENDENT_DISQUALIFIER_PRESENT`
- `RECOMMENDATION_LAYER_NO_TRADE`
- `IDO_ACTIONABLE_FALSE_WITHOUT_EXPLICIT_BLOCKER`
- `MISSING_TRADE_GEOMETRY`
- `MISSING_REGRET_THRESHOLD`
- `OBSERVATION_WINDOW_INCOMPLETE`

## No-Explicit-Blocker Diagnostics
Rows with no explicit blocker are isolated instead of being treated as blocker failures.

69.9.6 reports:
- recommendation action/state;
- whether the recommendation layer itself said `NO_TRADE`;
- whether captured actionability gates otherwise passed;
- whether the canonical IDO was still non-actionable;
- whether the case remains unexplained with the captured gates;
- trigger ID, decision ID, session, timestamp, direction, confidence, and market-open elapsed bucket.

A recommendation-layer `NO_TRADE` is a diagnostic reason, not a blocker-regret promotion.

## Target Absence Provenance
Missing regret thresholds are classified instead of collapsed into a generic unavailable state:
- `ENTRY_REFERENCE_MISSING`
- `EXPLICIT_TARGET_PRESENT_BUT_NOT_DIRECTIONALLY_FAVORABLE`
- `NO_EXPLICIT_PERSISTED_TARGET_OR_GOVERNED_MARGIN`

No support/resistance level is promoted into a synthetic target.

## Legacy 69.9.4/69.9.5 Regret Semantics
The existing `abstention_regret.potential_blocker_regret` remains a movement-qualified candidate statistic.

For trade-eligibility claims, the authoritative 69.9.6 surface is:

`counterfactual_regret.POTENTIAL_BLOCKER_REGRET`

This prevents a movement-qualified historical case with unknown actionability-window authority from being misrepresented as an actual missed trade.

## Dashboard
Premium Discipline now surfaces:
- Counterfactual Trade Eligibility summary;
- blocker × session actionability evidence coverage;
- qualified regret counts;
- dominant disqualification reasons;
- current-cutoff reference warning;
- no-explicit-blocker diagnostic rows.

## Authority
69.9.6 does not:
- change `THESIS_INVALIDATED`;
- change `THESIS_CONFLICTED`;
- change conviction thresholds;
- change entry cutoff;
- change consensus weights;
- activate calibration;
- grant execution authority;
- mutate broker state.
