# APEX 19.2–19.5 Implementation Report

## Release identity
- Final runtime: `12.5.0_ADAPTIVE_LEARNING_ENGINE_V2`
- Baseline: APEX 19.1 complete repository supplied by the user
- Database migration: not required

## APEX 19.2 — Institutional Dealer Positioning Engine
Added a read-only synthesis layer for gamma flip/zero gamma, call wall, put wall, net GEX, dealer delta, Vanna, Charm, hedging pressure, pin risk, squeeze probability, and volatility regime. The engine consumes existing APEX data only and performs no network or broker mutation.

## APEX 19.3 — Institutional Options Flow Intelligence
Added quality scoring, opening/closing inference, sweep/block classification, repeated institutional activity, persistence, clustering, speculation-versus-hedge inference, trap detection, and directional flow weighting. Intent fields are explicitly labeled as inference.

## APEX 19.4 — Institutional Probability Engine
Added bounded probabilities for new daily highs/lows, overnight range breaks, trend/range day, expected remaining range, expected close location, and confidence intervals. Stale data is flagged and barred from execution use.

## APEX 19.5 — Adaptive Learning Engine v2
Added outcome-based setup, regime, and time-of-day analysis; exclusion of `NOT_EXECUTABLE` records; minimum-sample readiness; bounded weight-change suggestions; and explicit human approval. Suggested weights are never applied automatically.

## Integration
- Eight read-only APIs registered in the production Flask app.
- Compact Mission Control panel added.
- Release manager updated to the final runtime identity.
- Existing 19.0 and 19.1 engines remain compatible.
- No execution toggle, broker permission, or trading safety contract was changed.
