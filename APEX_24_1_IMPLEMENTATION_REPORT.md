# APEX 24.1 — Institutional Portfolio & Risk Intelligence

Release identity: `17.1.0_INSTITUTIONAL_PORTFOLIO_RISK_INTELLIGENCE`

## Summary

Portfolio-level (not trade-level) risk intelligence, delivered as a
deterministic, read-only advisory layer built on top of the existing APEX 16.3
`portfolio_risk_intelligence` engine. Evolution, not replacement: the 16.3
engine is reused for base position normalization, net Greeks, position heat, and
breach detection; APEX 24.1 adds the institutional portfolio layer on top and
becomes the canonical owner of the advisory `/api/portfolio-risk/*` surface.

## Implemented

- Portfolio Risk Engine: portfolio Delta / Gamma / Theta / Vega, net directional
  exposure (notional + bias %), premium at risk, buying-power utilization, open
  risk, and remaining risk capacity / deployable capital. Multi-account ready
  (`accounts: [...]` folds into a single book).
- Risk Budget Manager: daily / weekly / monthly-drawdown / max-concurrent /
  max-premium-at-risk / max-directional-bias / max-portfolio-heat, all sourced
  from Configuration Governance environment variables. No hardcoded limits; each
  resolved limit reports its provenance (`ENVIRONMENT` vs `GOVERNED_DEFAULT`).
- Capital Allocation Intelligence: advisory `FULL_SIZE` / `HALF_SIZE` /
  `REDUCED_SIZE` / `NO_NEW_RISK` from Trading Brain confidence, forecast
  confidence, playbook quality, execution score, regime confidence, portfolio
  heat, existing exposure, and the governed risk budget.
- Correlation Intelligence: duplicate directional exposure, duplicate playbooks,
  duplicate strategy families, excess call / put concentration, and
  premium-selling concentration warnings.
- Opportunity Prioritization: ranks simultaneous opportunities by expected
  value, risk-adjusted return, capital efficiency, diversification benefit,
  institutional confidence, and execution quality.
- Mission Control 2.0: new `PORTFOLIO_INTELLIGENCE` panel + detail block +
  `/api/portfolio-risk/status` drill-down.

## API surface (one canonical namespace)

Owned by APEX 24.1:
`GET /api/portfolio-risk/status`, `GET /api/portfolio-risk/exposure`,
`GET /api/portfolio-risk/budget`, `GET /api/portfolio-risk/opportunities`,
`POST /api/portfolio-risk/evaluate`, `POST /api/portfolio-risk/allocation`,
`POST /api/portfolio-risk/prioritize`.

Preserved on the 16.3 persistence layer (reused, not duplicated):
`POST /api/portfolio-risk/record`, `GET /api/portfolio-risk/history`.

`/status` and `/evaluate` returned the richer 24.1 response while preserving the
16.3 top-level fields (`risk_state`, `net_greeks`, `total_open_risk`,
`permissions`, `advisory_only`, `broker_effect`, `orders_changed`,
`default_policy`, …) so existing consumers continue to function. `/evaluate` and
`/allocation` still accept the legacy `{"snapshot": {...}}` envelope.

## Registrar hardening

The APEX 24.1 route registration was moved OUT of the broad, non-fatal
`try/except` that wraps the APEX-10 production-route block. It now runs in a
dedicated block that:

- raises `RuntimeError` if the required module failed to import;
- catches Flask endpoint/route conflicts and re-raises them with an explicit
  duplicate-route diagnostic;
- verifies every canonical route registered (`verify_registered`) and raises
  `RuntimeError` listing any missing routes.

Silent registration failures for the required Portfolio Intelligence surface are
no longer possible.

## Safety

Advisory only. The module cannot place, modify, or cancel orders, cannot move
stops, cannot resize positions, and cannot bypass kill switches. Every response
reports `production_effect = NONE` and `broker_order_submission_enabled = false`.
