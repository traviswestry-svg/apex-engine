# APEX Trade Director Phase 19 — Institutional Decision Intelligence

## Purpose
Phase 19 creates a cached-only institutional decision committee that fuses the outputs of Trade Director Phases 11–18 into one explainable, fail-closed decision.

## New engine
`engine/trade_director_decision_intelligence.py`

The engine evaluates:

- Session Intelligence
- Market Memory
- Cross-Asset Intelligence
- Strategy Orchestration
- Options Intelligence
- Execution Desk readiness
- Multi-Timeframe Intelligence
- Institutional Flow Intelligence

## Outputs

- Weighted consensus score
- Dominant directional thesis
- Bullish, bearish, and neutral scenario probabilities
- Engine-by-engine voting records
- Institutional checklist
- Conflict analysis
- Hard blockers
- Decision narrative
- Advisory Trade Health and sizing posture

## Decision states

- `STRONG_BUY`
- `BUY`
- `WATCH`
- `REDUCE_RISK`
- `EXIT`
- `STAND_DOWN`

Directional actionable outputs are expressed as `STRONG_BUY_CALL`, `BUY_CALL`, `STRONG_BUY_PUT`, or `BUY_PUT`.

## Endpoint

- `GET /api/position/institutional-decision-intelligence`
- `POST /api/position/institutional-decision-intelligence`

POST accepts a normalized `context` or `evidence` object for deterministic testing. It performs no provider or broker requests.

## Dashboard
A new **Institutional Decision Center** shows:

- Consensus and confidence
- Committee recommendation
- Scenario probabilities
- Institutional checklist
- Engine voting committee
- Conflicts and hard authority blockers
- Decision narrative

The dashboard fetch workflow was also corrected to explicitly load Phase 18 flow data before rendering it.

## Safety
Phase 19 is advisory only. It cannot override:

- Session `STOP_TRADING`
- Phase 14 `STAND_DOWN`
- Phase 9 risk limits
- Phase 10 exact confirmation
- Phase 16 execution safeguards

It performs no startup work, background processing, provider fan-out, or broker activity. No new Render environment variables are required.

## Validation

- Python compilation passed
- Dashboard JavaScript syntax passed
- Strong bullish committee consensus passed
- Flow conflict downgrade passed
- Upstream `STAND_DOWN` authority passed
- Limited evidence fail-closed behavior passed
- Phase 13–18 regression tests passed
- Active Trade Director regression tests passed
- 58 selected tests passed
