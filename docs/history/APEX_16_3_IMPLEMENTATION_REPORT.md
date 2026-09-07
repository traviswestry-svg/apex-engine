# APEX 16.3 Implementation Report

## Release
APEX 16.3 — Portfolio & Risk Intelligence

## Objective
Add deterministic, advisory-only portfolio exposure and daily risk-governance controls to Live Mission Control without enabling broker or order mutation.

## Implemented
- `engine/portfolio_risk_intelligence.py`
- Immutable `portfolio_risk_snapshots` table
- Daily P&L and remaining loss-budget calculation
- Position heat and total open-risk calculation
- Net delta, gamma, theta, and vega aggregation
- Per-position market value and max-risk normalization
- SPX-compatible concentration analysis
- Daily trade-count, loss-count, open-position, heat, concentration, and per-trade risk gates
- Advisory lockout and permission matrix
- Mission Control composition and dashboard panel
- Status, evaluation, recording, and history APIs
- Six targeted tests

## Default risk policy
- Maximum daily loss: $1,000
- Maximum risk per trade: $2,000
- Maximum trades per day: 3
- Lockout after losses: 2
- Maximum position heat: 35% of account equity
- Maximum open positions: 3
- Symbol concentration: 100% to support the current SPX-only mandate

## Safety
The engine is read-only and advisory. It does not submit, replace, cancel, resize, or close orders. Risk reduction and closing permissions remain available even when a lockout is recommended.
