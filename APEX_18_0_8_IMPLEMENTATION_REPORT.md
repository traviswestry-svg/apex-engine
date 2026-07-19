# APEX 18.0.8 — Premium Discipline Command Center

Runtime version: `11.0.6_PREMIUM_DISCIPLINE_COMMAND_CENTER`

## Objective

Provide an operational command center for the Premium Discipline, Trade Refusal Replay, and Adaptive Refusal Calibration capabilities introduced in APEX 18.0.5–18.0.7.

## Delivered

- New page: `GET /apex_os/premium_discipline`
- New aggregate API: `GET /api/premium_discipline/command-center`
- Current premium eligibility, score, threshold, blockers, and headline
- Approval/refusal scorecard
- Replay precision, protected refusals, missed winners, pending replays, and modeled counterfactual P&L
- Active governed threshold and factor weights
- Latest calibration recommendation and evidence counts
- Explicit operator controls for calibration runs and governed promotion
- Decision/replay ledger with parsed, UI-safe evidence
- Advisory-only and no-execution-authority declarations in both the API and UI

## Governance

The command center does not create broker orders and does not bypass hard premium-safety blockers. Calibration recommendations remain inert until an operator explicitly promotes an eligible recommendation through the existing governed promotion endpoint.
