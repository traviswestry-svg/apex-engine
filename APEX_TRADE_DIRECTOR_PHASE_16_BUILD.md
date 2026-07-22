# APEX Trade Director Phase 16 — Institutional Execution Desk

Phase 16 adds broker-neutral execution planning between Phase 15 contract selection and Phase 10 broker preview/confirmation.

## Capabilities
- Smart limit-price ladder: patient, balanced, assertive
- Bid/ask quality and spread analysis
- Maximum acceptable price and no-chase slippage guard
- Partial-fill, remaining-quantity, and lifecycle assessment
- Execution quality score
- Deterministic plan ID
- Dashboard Execution Desk
- GET/POST `/api/position/execution-desk`

## Safety
- No provider requests
- No broker calls
- No market orders
- No automatic cancel/replace
- Phase 9 risk controls remain authoritative
- Phase 10 exact confirmation remains mandatory
- Live execution remains disabled by default

## Environment
No new environment variables are required.
