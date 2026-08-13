# APEX Trade Director Phase 23 — Institutional Replay & Decision Laboratory

Phase 23 extends the Phase 22 Institutional Learning Ledger with a read-only decision laboratory.

## Added
- Historical decision-state reconstruction from archived evidence only
- Chronological engine timeline
- Decision-quality scorecard
- Bounded counterfactual simulations
- Alternative-strategy comparison
- Replay library and selected-case API
- Dashboard Replay & Decision Laboratory panel

## Safety
Phase 23 performs no live provider or broker calls, does not rewrite Phase 22 outcomes, does not alter Phase 20 authorization or Phase 21 management, and labels all non-observed outcomes as simulations or bounds.

## Endpoints
- `GET /api/position/replay-laboratory`
- `POST /api/position/replay-laboratory`
- `GET /api/position/replay-laboratory/library`
