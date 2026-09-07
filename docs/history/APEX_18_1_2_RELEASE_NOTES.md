# APEX 18.1.2 — Multi-Strategy Portfolio Optimizer
Runtime: `11.0.10_MULTI_STRATEGY_PORTFOLIO_OPTIMIZER`

Adds an advisory portfolio-construction layer over Institutional Premium Intelligence and Expectancy Intelligence. It selects a bounded combination of eligible positive-expectancy strategies, allocates contracts under portfolio, account, and daily-loss limits, blocks overlapping iron-condor exposure, penalizes correlated directional structures, and explains every inclusion and exclusion.

New APIs:
- `GET /api/premium_discipline/portfolio`
- `GET /api/premium_discipline/portfolio/allocation`
- `GET /api/premium_discipline/portfolio/risk`

The command-center payload now includes `portfolio_optimizer`. No broker execution authority was added.
