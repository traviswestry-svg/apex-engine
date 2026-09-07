# APEX 16.0 — Institutional Trading Desk Implementation Report

## Centerpiece
Institutional Order Flow Intelligence 2.0 (IOFI) is the canonical deterministic institutional-pressure layer for the Trading Desk.

## Implemented
- Ten-domain Institutional Pressure Score (IPS)
- Bullish/bearish bias and conviction classification
- Ranked evidence drivers and explicit conflicts
- Immutable institutional-pressure snapshots
- Immutable bias-transition history
- Unified Trading Desk dashboard composed with IMSE and IPE
- Read-only APIs for evaluation, recording, history, current state, transitions, and desk composition

## Pressure domains
Options sweeps, block conviction, dealer hedging, gamma structure, delta exposure, auction imbalance, volume profile, liquidity pressure, breadth/leadership, and ES/SPX confirmation.

## Safety
The engine is deterministic and advisory. It cannot mutate recommendations, confidence, risk, playbook selection, market state, or broker orders. Production effect is NONE.
