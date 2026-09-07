# APEX 18.1.3 — Portfolio Outcome Attribution & Replay
Runtime: `11.0.11_PORTFOLIO_OUTCOME_ATTRIBUTION`

Adds durable, idempotent capture of Multi-Strategy Portfolio Optimizer recommendations and post-session counterfactual replay. Each selected structure is graded from the original recommendation timestamp through the 4:00 PM ET settlement window. Contract-weighted modeled P&L is attributed by strategy and compared with the portfolio's original expected value.

## APIs
- `GET /api/premium_discipline/portfolio/outcomes`
- `POST /api/premium_discipline/portfolio/replay/run`

The command-center payload now includes the portfolio outcome scorecard. Portfolio and replay logic remain advisory and have no broker authority.
