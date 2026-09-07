# APEX 69.9.4 — Session-Conditioned Abstention Regret & Blocker Effectiveness Validation

## Purpose
69.9.4 evaluates whether APEX blockers are protective or potentially over-restrictive within the correct session, direction, confidence, and blocker-composition cohorts.

This release is observational. It does not change any blocker, threshold, confidence score, evidence weight, calibration state, execution authority, or broker state.

## Canonical Population
Abstention-regret analysis is restricted to:

`CANONICAL_DECISION` + `OBSERVATIONAL_NO_TRADE`

Actionable trades, non-actionable closed-market observations, Pine observations, and unlinked observations are not mixed into the abstention population.

## New API
`GET /api/triggers/abstention-regret?symbol=SPX`

The same result is also exposed inside:

`GET /api/triggers/predictive-validation?symbol=SPX`

Predictive validation advances to `apex.predictive_validation.v5`.
Abstention regret uses `apex.abstention_regret.v1`.

## Abstention Classification
Each canonically graded observational NO_TRADE is classified as:

- `ABSTENTION_SUCCESS`
  - the blocked directional thesis was canonically graded incorrect.

- `DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE`
  - the directional thesis was graded correct, but persisted evidence does not establish sufficient movement against an existing governed threshold.

- `POTENTIAL_BLOCKER_REGRET`
  - the directional thesis was graded correct and observed favorable excursion met an existing persisted movement threshold.
  - This is still not proof that an executable SPXW trade existed.

## Movement Threshold Contract
69.9.4 never invents a point threshold.

Threshold priority:
1. persisted directional `target1_reference`;
2. persisted `dynamic_state_policy.required_boundary_margin_points`;
3. `UNAVAILABLE`.

If no persisted threshold exists, blocker regret is not threshold-evaluable.

A threshold being met is necessary-not-sufficient evidence only. It does not prove:
- option premium availability;
- fill quality;
- stop viability;
- spread/slippage quality;
- executable entry timing;
- realized profitability.

## Observation Timing
Time-to-excursion diagnostics use only persisted `trade_trigger_price_observations`.

No missing path is interpolated.

Reported timing includes:
- first favorable excursion;
- first adverse excursion;
- first favorable excursion meeting the persisted threshold.

## Session-Conditioned Blocker Analysis
The build adds:
- blocker × session;
- blocker × direction × session;
- blocker × confidence × session;
- isolated blocker vs simultaneous blockers × session;
- MARKET_OPEN elapsed-time cohorts:
  - `OPENING_0_15`
  - `OPENING_15_30`
  - `OPENING_30_60`
  - `LATER_MARKET_OPEN_60_PLUS`

Each cohort reports:
- graded observations;
- blocked thesis directionally correct / incorrect;
- abstention success rate;
- potential blocker regret count and rate;
- threshold-evaluable observations;
- MFE / MAE;
- time to first favorable / adverse excursion;
- time to threshold favorable excursion.

## Dashboard
Premium Discipline Command Center now surfaces:
- Session-Conditioned Abstention Regret summary;
- Blocker × Session table;
- MARKET_OPEN window × blocker table;
- blocker multiplicity × session table;
- explicit counterfactual / non-execution guardrails.

## Governance
69.9.4 does not:
- modify `THESIS_INVALIDATED`;
- modify conviction thresholds;
- modify confidence;
- change consensus weights;
- activate calibration;
- grant execution authority;
- mutate broker state.

Potential blocker regret remains a diagnostic hypothesis requiring further execution-quality evidence before any behavioral promotion.
