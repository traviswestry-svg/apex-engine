# APEX Institutional OS 6.0.5 — Market Health Integration Fix

## Scope
Adds a production diagnostic endpoint to distinguish normal closed-market null values from real data integration problems.

## Changes

### Added
- `/api/market_health` endpoint.
- Component health checks for Session, Polygon, QuantData, Charts, ES Feed, Gamma, Flow, Structure, Trend, Risk, and Execution.
- Closed-market guidance showing which nulls are expected while the market is closed.
- Overall readiness labels:
  - `READY_FOR_LIVE_SESSION`
  - `READY_FOR_OPEN`
  - `READY_WITH_WARNINGS`
  - `NEEDS_ATTENTION`

### Fixed
- Risk engine now receives canonical SPX price from the flow intelligence object when market structure price is unavailable.
- Prevents Risk from showing `No price available` when QuantData already returned `stock_price`.

### Version
- Updated app version to `6.0.5_MARKET_HEALTH_INTEGRATION`.

## Verify
After deploy, open:

```text
/api/market_health
/api/institutional_os?ticker=SPX&heatmap=0
/api/charts/state
/api/diagnostics/gamma
```

Expected Sunday/closed-market behavior:
- Session should show market closed.
- Gamma should be OK if QuantData returns walls.
- Flow should be OK if QuantData returns scores.
- Structure/Execution may show waiting/closed-session status.
- ES Feed may show ES unavailable if futures feed is not configured.
