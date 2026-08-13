# APEX Trade Director Phase 29

## Institutional Portfolio & Capital Allocation Intelligence

Phase 29 adds an advisory portfolio supervision layer above the single-trade decision stack. It aggregates open-position risk, notional exposure, Greeks, symbol/strategy/directional concentration, remaining daily-loss capacity, and portfolio risk utilization before recommending a bounded candidate allocation.

### New engine

- `engine/trade_director_portfolio_allocation.py`

### Capabilities

- Portfolio risk aggregation
- Capital-budget utilization
- Symbol, strategy, and direction concentration
- Aggregate delta, gamma, vega, and theta exposure
- Confidence-weighted candidate allocation
- Portfolio stress scenarios
- Fail-closed allocation blockers

### Safety boundary

Phase 29 is advisory only. It cannot authorize trades, increase hard risk limits, submit or modify orders, or interact with a broker. Its recommendations may only reduce or block allocation before Phase 20 authorization.

### APIs

- `GET /api/portfolio/allocation`
- `POST /api/portfolio/allocation`
- `POST /api/portfolio/stress-test`

### Validation

- Unit tests cover aggregation, concentration reduction, exhausted-budget blocking, and advisory-only stress testing.
