# APEX 66.3.1 — Decision Adapter & State Semantics Hardening

## Objective
Harden the APEX 66.3.0 Decision Reasoning Consolidation foundation by binding normalized EngineOpinion objects to the actual production schemas already emitted by existing APEX engines and by correcting session/evidence state semantics discovered during live weekend validation.

## Changes
- Zero eligible evidence now resolves to `UNKNOWN`, never `NEUTRAL`.
- Missing/unavailable providers emit `ABSTAIN` with `freshness_state=UNAVAILABLE`.
- Available engines that have no directional opinion may abstain without being classified as unavailable.
- `unavailable_engines` and `unavailable_sources` are populated from provider availability semantics.
- Canonical session resolution now consumes existing APEX session state and falls back to `live_operations.session_state()` when the composed snapshot has no session field.
- Closed-session canonical decisions report `MARKET_CLOSED`, `NO_TRADE`, `UNKNOWN` direction, and remain fail-closed.
- Canonical actionability now requires an actual `BULLISH` or `BEARISH` direction; `UNKNOWN` can never become actionable.
- Existing production schemas are adapted directly for Institutional Intelligence, Auction, Market Structure, Flow, Liquidity, Dealer Positioning, Breadth/Market Drivers, and Execution Intelligence.
- Thesis `known_unknowns` is deduplicated.

## Production schema mappings
- Institutional Intelligence: `institutional_bias|bias|direction`
- Auction: `auction_state.direction|auction_state.state`, acceptance, POC migration, existing bias fields
- Market Structure: canonical `direction|bias`, with existing Institutional Intelligence nested market-structure fallback
- Flow: canonical market-state `flow_bias`, Flow Intelligence `flow_bias|flow_intent`
- Liquidity: `institutional_intent.direction|state`, trade-director alignment, liquidity-race fallback
- Dealer: `bias|direction`, delta bias, dealer hedging pressure
- Breadth: `market_bias|breadth` from existing breadth/market-driver outputs
- Execution: `approved_side|side|direction`, or directional execution-state labels

## Guardrails
- No new analytical engine.
- No broker/execution boundary changes.
- No database migration.
- No learning-history mutation.
- No historical probability fabrication.
- Correlation penalties remain configured architecture priors, not historical claims.

## Validation
- APEX 65–66 integrity/HLCE/decision suite: 85 passed, 1 skipped, 0 failed.
- Execution-boundary/risk regression suite: 23 passed, 0 failed.
- Focused 66.3.0/66.3.1 reasoning semantics: 14 passed, 0 failed.
- Python compilation passed for changed modules and full repository compilation pass.
- The single skip is the pre-existing isolated-runtime Flask import limitation.

## Database
Schema version remains 5. No migration required.
