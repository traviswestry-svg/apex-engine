# APEX Trade Director Phase 38 Build

## Phase
**Phase 38 — Decision Quality & Alert Integrity**

## Purpose
Phase 38 converts the latest SPX 0DTE system-design research into production-safe advisory controls. It separates directional prediction from executable alert quality, prevents raw contract volume from being treated as institutional conviction, exposes decision-boundary margin, and adds hysteresis-aware alert governance.

## New Engine
- `engine/trade_director_decision_quality.py`

### Flow Participation Intelligence
Reports:
- premium-weighted participation
- delta-adjusted notional when delta is available
- small-lot share
- block share
- opening-intent share
- top-three-strike concentration
- participant mix

Raw contract volume is never independently treated as conviction.

### Decision Boundary and Hysteresis
Reports:
- entry threshold
- lower active-position exit threshold
- applied threshold
- margin from the active boundary
- required confidence improvement
- explicit hysteresis width

Alerts touching a threshold without a five-point stability margin remain `WATCH_ONLY`.

### Alert Quality Governance
Alerts fail closed for:
- closed market
- stale or missing data
- absent directional consensus
- poor or unavailable liquidity
- confidence below the decision boundary
- weak execution or position quality
- small-lot-dominated flow
- dispersed strike participation
- insufficient decision-boundary margin

`STAND_DOWN` and abstention remain valid governed outputs.

### Policy Quality Contract
The engine accepts but never fabricates:
- actionable-alert precision
- next-executable-price return
- slippage
- alert latency
- maximum adverse excursion

Until those fields are collected, policy quality reports `COLLECTING`.

## API
- `GET|POST /api/decision-quality`
- `GET|POST /api/decision-quality/flow-participation`

GET uses the latest cached APEX result. POST evaluates a supplied normalized snapshot.

## Mobile Alert Integration
Phase 37 now honors Phase 38 `alert_eligible`. A Phase 38 policy suppression prevents a Momentum Burst Telegram alert but never creates, modifies, or closes an order.

## Safety
- Advisory only
- Cached normalized inputs only
- No provider calls
- No broker calls
- No trade calls
- No fabricated policy statistics
- Next-executable-price grading required
