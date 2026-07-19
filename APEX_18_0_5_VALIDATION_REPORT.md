# APEX 18.0.5 Validation Report

## Result
**PASS**

## Automated validation
- Command: `PYTHONPATH=. pytest -q`
- Result: **929 passed**
- Runtime: 10.86 seconds

## Focused premium-discipline validation
- Clean contained market approves eligible credit structures.
- Closed sessions refuse premium selling.
- Active breakout/price-discovery conditions create a hard refusal.
- Unpriceable and non-tradeable candidates cannot pass on score alone.
- Debit structures and explicit `NO_TRADE` candidates are classified as not applicable.
- Governed threshold is enforced.
- Decision ledger is idempotent.
- New APIs register and return HTTP 200 without disturbing existing routes.

## Regression status
Existing premium strategy, chain-pricing, release-manager, execution, observability, configuration-governance, recommendation-ledger, and full institutional test suites passed.
