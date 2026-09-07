# APEX 19.1 Implementation Report

## Release
- Product release: APEX 19.1 — Institutional Market Structure Engine
- Runtime: `12.1.0_INSTITUTIONAL_MARKET_STRUCTURE_ENGINE`
- Baseline: user-supplied updated APEX 19.0 repository
- Database migration: not required

## Implemented capabilities
- Multi-timeframe profile normalization for 1m, 5m, 15m, session, previous-day, and daily profiles where supplied.
- Cross-profile POC/VAH/VAL confluence detection.
- POC and value-area migration classification.
- Opening-type detection: Open Drive, Open Test Drive, Open Rejection Reverse, Open Auction in Range, and Open Auction in Range Expansion.
- Poor-high/poor-low, buying-tail, selling-tail, single-print, and auction-completion diagnostics.
- Value acceptance/rejection classification.
- Trend-day versus balance-day probability assessment.
- Institutional support, resistance, LVN fast-zone, HVN, and target mapping.
- Read-only APIs and compact Mission Control Market Structure panel.
- Unified 19.0 intelligence now consumes the 19.1 market-structure output.

## Safety
No network calls or broker mutations were added. Automatic execution remains disabled. Existing execution switches, confirmation requirements, stale-data safeguards, and broker controls remain authoritative.

## Baseline compatibility correction
The uploaded baseline contained two failing portfolio-attribution tests. Compatibility was restored by preserving both `pending` and `pending_portfolios`, standardizing attribution as `{"positions": [...]}`, and retaining legacy list-reading support in calibration logic.
