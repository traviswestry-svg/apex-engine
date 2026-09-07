# APEX 68.6.0 — Decision Outcome Attribution & Abstention Effectiveness

## Objective
Close the measurement gap between what APEX recommends, what it rejects, and what the market subsequently does. 68.6 adds one observational effectiveness layer over the existing canonical evidence pipeline; it does not create another decision engine or execution authority.

## What changed
- Every canonical decision snapshot now freezes an attribution context containing action class, direction, entry reference, confidence, and decision-time gate states.
- A separate attribution grader follows actionable and abstained decisions through the configured forward horizon.
- Abstentions remain excluded from `grading_results`; their counterfactual outcomes are stored only in `decision_effectiveness_attribution`, preventing contamination of 68.3–68.5 calibration.
- Directional abstentions with a valid decision-time entry reference are measured for MFE, MAE, terminal directional move, missed-opportunity rate, and protective-abstention rate.
- Gate effectiveness reports opportunity cost after a block, protection after a block, and win rate after a passed gate.
- Entry quality recognizes `OPTIMAL_ENTRY` and `EARLY_ENTRY` from bounded post-decision evidence. `LATE_ENTRY` and `CHASED_ENTRY` require explicit decision-time evidence; APEX does not fabricate those labels from future prices.
- Exit effectiveness reads completed Trade Director learning outcomes and computes capture efficiency only when a stored captured/realized move and MFE both exist.

## API
- `GET /api/effectiveness`
- `GET /api/effectiveness/attribution`
- `GET /api/effectiveness/abstentions?limit=100`
- `GET /api/effectiveness/exits?limit=500`

## Safety boundaries
68.6 is observational only. It does not change live thresholds, confidence, consensus weights, alert suppression, WATCH_ONLY state, risk, broker behavior, or execution authority. Findings do not auto-promote through the 68.5 activation boundary; any future policy change still requires governed human review.
