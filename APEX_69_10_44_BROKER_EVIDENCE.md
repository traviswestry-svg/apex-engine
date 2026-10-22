# APEX 69.10.44 — TradersPost Broker Evidence Integration & Paper Fill Reconciliation

## Integration truth
TradersPost documents that its developer API is not currently available and its webhook does not return order identifiers or broker account/position state. TradersPost also announced CSV exports in its November 22, 2025 release notes; the CSV columns are not guaranteed and must be explicitly mapped. Do not interpret CSV or webhook receipt as broker-confirmed executions. The built-in TradersPost paper broker is a simplified simulator, not suitable for measuring realistic strategy P&L.

References:
- https://docs.traderspost.io/docs/developer-resources/api-planned-later
- https://docs.traderspost.io/docs
- https://docs.traderspost.io/releases/old-releases/november-22nd-2025
- https://docs.traderspost.io/docs/learn/platform-concepts/paper-trading

## Changes
- `engine/execution/traderspost_export_evidence.py`: Server-side offline CSV intake for explicit-column-mapped exports, exact canonical decision and contract matching, bounded payload, SHA-256 file/row digests, duplicate rejection, atomic SQLite commits and permanently quarantined events. No API keys, scraping, browser automation or order execution.
- `engine/execution/trade_routes.py`: Initialize the export inbox on application startup and report redacted inbox status on the authenticated GET `/api/paper/traderspost/ledger-health` endpoint. No upload/write HTTP routes are exposed.
- Registry and release manifest version aligned at 69.10.44.
- Regression tests cover quarantine, persistence, malformed data and mismatches.

## What remains blocked
`broker_reconciliation_operational=false` and `ready_for_unattended_orders=false` unconditionally. `fill_verified=false` for CSV evidence; no trusted broker order feed, fill certification, P&L promotion, exit reconciliation or enforceable realized loss cap. No paper orders or real trades are sent.

## Offline developer usage
`stage_csv(csv_bytes, column_map=..., lifecycle_by_decision=..., db_path=...)` is an internal Python function. It is **not** exposed as a dashboard or API upload because export authenticity and identity are not independently established. `column_map` must name each required CSV column; `lifecycle_by_decision` must be supplied by trusted server code, not from the CSV. Review the format and the security boundary before invoking in production. Never submit credentials or arbitrary CSV file paths through HTTP.

## Deployment gates
Run full GitHub CI, configuration/release governance, gamma transition regressions, and route/security tests on the repository with installed application dependencies. Confirm persistent `/data` storage, no outstanding merge conflicts and that the 69.10.44 metadata is canonical. The patch is not production certified based solely on selected local tests.

## Suggested next step
For true independently retrievable order/position/fill evidence, evaluate connecting TradersPost to a **paper broker with a documented read-only order/position API** (for example a suitable supported provider) and read that broker directly with account-scoped credentials. Keep this built-in paper account in diagnostics-only mode until such integration is designed, tested, and approved.
