# APEX 69.10.43 — Paper Execution Reconciliation & Lifecycle Validation

This release adds a **quarantine-only** broker evidence journal, not a live TradersPost account adapter. Webhook delivery never proves an order or fill. Evidence can be submitted **only by a server-injected trusted_reader callable**, not by a new HTTP endpoint, and even authenticated records remain QUARANTINED_UNRECONCILED pending an independently validated account/position snapshot and risk enforcement.

## Operational changes
- During route registration initialize the reconciliation evidence schema on the existing paper ledger (`/data/apex_traderspost_paper.sqlite3` by default), preserving existing records.
- GET `/api/paper/traderspost/ledger-health` includes `reconciliation_journal`, `quarantined_events`, `reconciliation_initialization_error`, and explicit `broker_reconciliation_detail=NO_VERIFIED_TRADERSPOST_BROKER_READER`.
- No dispatch authority, broker fill promotion, verified realized P&L, or daily loss enforcement is introduced. The existing `dispatch` fail-closed guard remains.
- Strict canonical bound decision/contract matching, authenticated-source assertions, positive finite prices, timezone-aware timestamps and unique broker event IDs are required for journal staging.
- **Do not** treat `authenticated=True` from an arbitrary callable as validated broker authority: this API is for internal controlled testing and staging only, not production fill promotion.

## Verification
`python -m pytest -q tests/test_apex_69_10_43_paper_reconciliation.py tests/test_apex_69_10_42_runtime_ledger.py tests/test_apex_69_10_41_canonical_ledger.py tests/test_apex_69_10_40_paper_foundation.py`

Selected governance/gamma checks: 29 passed, 1 fails because `flask` is not installed in the current execution environment. Full repository CI not certified. Deploy only after CI passes against the current main branch.

## Remaining work
- Obtain and validate a TradersPost paper account order/fill/position API or other independently authenticated authoritative source; do not infer fills from webhook success.
- Cross-check partial fills, contract quantities, entry/exit timestamps, cash ledger and daily realized P&L with a verified source.
- Explicitly authorize any future execution functionality through separate release governance. Maintain paper-only controls.
