# APEX Trade Director Phase 15 — Options Intelligence Engine

## Purpose
Phase 15 converts Phase 14 strategy-family selection into contract-level advisory intelligence when a normalized option chain is already cached or explicitly supplied.

## Added
- `engine/trade_director_options_intelligence.py`
- `GET /api/position/options-intelligence`
- `POST /api/position/options-intelligence` for deterministic testing/ranking of supplied normalized contracts
- Options Intelligence Center in `templates/assistant.html`

## Intelligence
- Strategy compatibility
- Delta targeting
- Greeks availability and interpretation
- Bid/ask spread quality
- Volume and open-interest scoring
- Expected-move alignment
- Expiration and strike guidance
- Best candidate plus alternatives

## Fail-closed behavior
If no normalized chain is cached, Phase 15 returns `CHAIN_REQUIRED` and contract-characteristic guidance. It does not fabricate symbols, strikes, prices, Greeks, or expirations.

## Safety
- No startup work
- No provider requests
- No broker requests
- No order preview or transmission
- Phase 9 risk and Phase 10 confirmation remain authoritative
- No new environment variables
