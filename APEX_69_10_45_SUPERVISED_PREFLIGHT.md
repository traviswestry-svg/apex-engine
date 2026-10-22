# APEX 69.10.45 — Supervised Paper Order Preflight

This patch must be applied on top of deployed 69.10.44. The available repository source was 69.10.42 plus the 69.10.43 and 69.10.44 changed-file patches; rebase against GitHub main before merging.

## Scope
- GET `/api/paper/traderspost/order-preflight`: session-authenticated read-only readiness check.
- POST same route: operator-token-authenticated diagnostic validation of an exact proposed SPX options contract and persisted decision; **never sends orders**. Requires `X-APEX-Paper-Token`; browser global authentication still applies.
- Reject missing decision evidence, contract identity mismatch, bad prices/size, entries outside 09:35–11:30 ET.
- Retains permanent fail-closed blockers for missing trusted execution authority, broker fills, exit reconciliation, daily realized-loss enforcement.
- Does not remove `test:true` from connectivity probes or change the dispatch() hard stop.

## Operational note
TradersPost test webhooks cannot execute trades. Live paper order dispatch is intentionally unavailable until a safe broker evidence/reconciliation strategy exists. The manual mode and test signal checks must be inspected separately. Do not enable Auto Submit or use client flags as authorization.

## Validation
See accompanying regression test. Production CI and GitHub main-base merge not verified.
