# APEX Morning Readiness False-Failure Fix

## Root cause

The execution snapshot treated an absent premium recommendation as though live option quotes had already been requested and failed to arrive. At the same time, an unevaluated chain with status `UNKNOWN` was classified as a passed chain gate.

This produced the contradictory live-session checklist:

- Chain Gate: READY
- Quotes Present: FAIL
- Quotes Fresh: FAIL
- Liquidity: FAIL
- Recommendation: WAITING

The quote and liquidity checks are downstream of candidate selection. Before a recommendation/chain exists, those checks are not failures; they are waiting states.

## Fix

- Added explicit `chain_evaluated` and `quotes_expected` execution checks.
- Prevented `UNKNOWN` chain status from being classified as a passed gate.
- Made quote freshness require an actual quote and a positive quote age.
- Made liquidity readiness require an actual quote.
- Changed Chain Gate, Quotes Present, Quotes Fresh, and Liquidity to `WAITING` while the market is open but no candidate recommendation exists.
- Preserved true `FAIL` behavior when a candidate exists and its required chain/quotes/liquidity are unavailable, stale, blocked, or below threshold.

## Validation

- Python syntax compilation: passed.
- Targeted tests: 22 passed.
- Full pytest collection: not completed because Flask is not installed in the validation environment (`ModuleNotFoundError: No module named 'flask'`).
