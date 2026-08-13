# APEX Trade Director Phase 14

## Strategy Orchestration & Opportunity Ranking

Phase 14 converts the intelligence produced by Phases 1–13 into an advisory, ranked SPX strategy-family queue.

### Strategies ranked
- Long call
- Call debit spread
- Bull put credit spread
- Long put
- Put debit spread
- Bear call credit spread
- Iron condor
- Stand down

### Inputs
- Trade Director confidence and health
- Phase 11 session mode and remaining risk capacity
- Phase 12 predictive session plan
- Phase 13 cross-asset bias, regime, coverage, and divergences
- Historical trade records when available

### Endpoint
`GET /api/position/strategy-orchestration`

### Safety boundary
Phase 14 does not select contracts or strikes, request option-chain data, preview orders, contact a broker, or transmit orders. Phase 9 and Phase 10 remain authoritative for execution readiness, confirmation, and broker control.

### Environment
No new environment variables are required.
