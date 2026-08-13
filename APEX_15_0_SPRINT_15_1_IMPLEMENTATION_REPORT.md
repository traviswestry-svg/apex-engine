# APEX 15.0 Sprint 15.1 — Institutional Market State Engine

## Summary
Implemented the Institutional Market State Engine (IMSE) as the canonical deterministic market-context layer for APEX 15.0.

## Capabilities
- Twelve-state institutional taxonomy covering auction, gamma, volatility, participation, and liquidity.
- Deterministic state scoring from the supplied decision-time snapshot only.
- Active state, confidence, secondary states, driver set, and Regime Stability Index.
- Immutable state snapshots with SHA-256 identity.
- Immutable state-transition records.
- Current, history, transition, classification, record, and dashboard APIs.
- New IMSE dashboard.
- Decision Intelligence Center integration.
- Institutional Replay 2.0 integration.
- Cross-Examination MARKET_STATE question routing.

## Taxonomy
BALANCED_AUCTION, TREND_AUCTION, DOUBLE_DISTRIBUTION, FAILED_AUCTION, GAMMA_PIN, GAMMA_EXPANSION, GAMMA_TRANSITION, LOW_VOLATILITY_COMPRESSION, HIGH_VOLATILITY_EXPANSION, INSTITUTIONAL_ACCUMULATION, INSTITUTIONAL_DISTRIBUTION, THIN_LIQUIDITY.

## Safety
IMSE is observational and read-only relative to trading behavior. It does not mutate recommendations, confidence, conviction, risk, execution, champion/challenger, canary routing, promotion governance, or releases.
