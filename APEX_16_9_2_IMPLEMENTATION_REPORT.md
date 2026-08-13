# APEX 16.9.2 — Broker Integration Completion

## Objective
Complete the market-data-to-strategy integration discovered during live E*TRADE sandbox validation. The account and option-chain paths were healthy, but premium-strategy pricing could still report an unpriceable structure because it depended on a different provider path.

## Implemented
- Added `engine/broker_integration_completion.py`.
- Added read-only `/api/broker/etrade/diagnostics`.
- Added independent states for OAuth, accounts, option chain, quotes, Greeks, preview and execution.
- Added chain latency, quote coverage and Greek/IV coverage reporting.
- Added canonical field-source metadata to the SPX chain response.
- Added chain coverage counts to the SPX chain response.
- Routed Premium Strategy pricing through Polygon/Massive first with E*TRADE fallback.
- Updated Trade Command Center with a Diagnostics action and detailed source/coverage display.
- Preserved confirmation-gated execution and disabled automatic execution.

## Safety
The diagnostics layer is read-only. It cannot preview, place, cancel, replace or modify an order.
