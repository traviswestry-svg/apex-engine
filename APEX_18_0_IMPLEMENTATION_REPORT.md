# APEX 18.0 — Adaptive Intelligence Implementation Report

## Scope
APEX 18.0 adds a governed adaptive-learning layer without enabling unattended execution or automatic live parameter mutation.

## New engine
`engine/adaptive_intelligence.py`

Capabilities:
- Immutable historical session memory
- Deterministic session feature normalization
- Similar-session retrieval using cosine similarity
- Confidence calibration with minimum-sample protection
- Governed playbook rankings
- Institutional Edge Score with blocker caps
- Immutable post-trade self-evaluation
- Immutable daily journal generation
- Advisory-only adaptive dashboard

## Integration
- Registered Adaptive Intelligence APIs in `engine/institutional_roadmap_routes.py`.
- Added Adaptive Intelligence to the 17.1 Trading Desk aggregation model.
- Added an Adaptive Intelligence Center to the Institutional Trading Desk UI.

## Governance
- No automatic strategy-weight mutation
- No broker mutation
- No automatic order submission
- Human confirmation remains mandatory
- Calibration is refused below 30 validated observations
- Missing history is displayed as collecting/unavailable rather than synthesized
