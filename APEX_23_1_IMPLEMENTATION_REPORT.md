# APEX 23.1 — Institutional Regime Intelligence

Release identity: `16.1.0_INSTITUTIONAL_REGIME_INTELLIGENCE`

APEX 23.1 adds a read-only regime layer above the APEX 23.0 Trading Brain. It classifies market conditions, tracks transitions, publishes risk posture, recommends advisory engine-weight multipliers, and provides playbook guidance without changing broker permissions, production weights, or kill-switch authority.

## Regimes
- TREND_EXPANSION
- BALANCED_ROTATION
- MEAN_REVERSION
- VOLATILITY_EXPANSION
- COMPRESSION
- TRANSITION

## APIs
- `/api/regime-intelligence/status`
- `/api/regime-intelligence/diagnostics`
- `/api/regime-intelligence/scores`
- `/api/regime-intelligence/transition`
- `/api/regime-intelligence/guidance`

## Mission Control
Mission Control 2.0 now exposes the primary regime, confidence, transition state, and risk posture with a diagnostics drill-down.
