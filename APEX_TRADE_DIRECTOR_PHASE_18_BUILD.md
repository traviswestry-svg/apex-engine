# APEX Trade Director Phase 18 — Institutional Flow Intelligence

Phase 18 converts cached options-flow and market-microstructure evidence into a guarded institutional-intent assessment.

## Added

- `engine/trade_director_flow_intelligence.py`
- `tests/test_trade_director_phase18.py`
- `GET|POST /api/position/institutional-flow-intelligence`
- Institutional Flow Intelligence dashboard panel

## Intelligence

- Sweep, block, split, and trade normalization
- Ask/bid aggressor interpretation
- Call/put directional intent classification
- Opening/closing evidence handling without fabrication
- Premium-weighted institutional bias
- Flow clustering by side, strike, expiration, and intent
- Dealer gamma/hedging context
- Volume-profile migration confirmation
- Cross-asset and multi-timeframe conflict detection
- Liquidity-seeking interpretation
- Trade Health and sizing posture advisory

## Gates

- `INSTITUTIONAL_CONFIRMATION`
- `MONITOR_FLOW`
- `MIXED_FLOW`
- `FLOW_CONFLICT`
- `DATA_LIMITED`
- `STAND_DOWN`

## Safety

Phase 18 is cached-only. It makes no provider or broker request, starts no worker, fabricates no flow or opening intent, and cannot override Phase 9 risk, Phase 10 confirmation, Phase 14 `STAND_DOWN`, or Phase 16 execution controls.

No new environment variables are required.
