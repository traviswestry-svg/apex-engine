# APEX 46.0 — Adaptive Learning Engine

## Added
- Outcome ledger for graded bullish and bearish decisions.
- Feature snapshots for liquidity, order flow, delta, auction, structure, momentum, gamma, and VWAP.
- Confidence calibration diagnostics including win rate and Brier score.
- Bounded weight proposals with a maximum 20% change per feature before normalization.
- Shadow-learning mode until sufficient graded outcomes exist.
- Optional active bounded mode only after the activation sample threshold and explicit environment enablement.
- Full recalibration audit log and dashboard transparency.
- Market Narrative 45 can consume active adaptive weights when safeguards authorize them.

## API
- `GET /api/adaptive-learning`
- `POST /api/adaptive-learning/outcome`
- `POST /api/adaptive-learning/recalibrate`
- `GET /api/adaptive-learning/summary`

## Default safeguards
- 30 graded outcomes before weight proposals.
- 100 graded outcomes before activation eligibility.
- Activation requires `APEX_ADAPTIVE_ACTIVATE=1`.
- Default mode does not change live scoring.
- No order placement, modification, cancellation, or execution authority.
