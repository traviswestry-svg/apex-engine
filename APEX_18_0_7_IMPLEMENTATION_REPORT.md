# APEX 18.0.7 — Adaptive Refusal Calibration

Runtime version: `11.0.5_ADAPTIVE_REFUSAL_CALIBRATION`

## Scope

This release converts graded Trade Refusal Replay outcomes into bounded, explainable policy recommendations for the Premium Discipline gate.

## Capabilities

- Reads graded refusal outcomes from the durable Premium Discipline ledger.
- Separates capital-protecting refusals from missed winners.
- Requires a governed minimum sample before issuing a recommendation.
- Recommends bounded threshold changes between 55 and 80.
- Recommends normalized factor-weight changes for Auction, Regime, Gamma, Flow, Volatility, and Candidate Quality.
- Stores immutable calibration runs and their evidence.
- Keeps recommendations non-operational until explicitly promoted.
- Supports one active promoted policy at a time.
- Applies promoted thresholds and weights to future premium eligibility evaluations.
- Preserves all hard safety blockers; calibration cannot override closed-session, unpriceable, non-tradeable, or active price-discovery gates.

## API

- `GET /api/premium_discipline/calibration`
- `POST /api/premium_discipline/calibration/run`
- `POST /api/premium_discipline/calibration/promote`

The existing replay and Premium Discipline endpoints remain available.

## Safety

The release is advisory and governance-controlled. It cannot place, modify, cancel, or authorize broker orders. Promotion changes only the Premium Discipline scoring policy and requires an explicit API action.
