# APEX 69.10.33 — Open Discovery Counterfactual Discrimination & Shadow Eligibility

- Read-only RTH OPEN_DISCOVERY (09:30–10:00 ET) research surface.
- Uses canonical market-calendar eligibility from 69.10.32.1.
- Uses only frozen decision-time attribution evidence; MFE/MAE/directional outcome are excluded from candidate features.
- Applies identical anchor-horizon analytical deduplication and chronological session-date holdout.
- Candidate minimums: train support 6, train missed 2, holdout support 3, train lift >= 1.25, holdout lift > 1.0.
- `SHADOW_ELIGIBLE_CANDIDATE` is analytical only; canonical `NO_TRADE` is unchanged.
- Structural-map fields absent from immutable attribution rows are not reconstructed.
- No threshold, calibration, learning-eligibility, decision-authority, broker, or execution changes.
- Release metadata ratcheted to 69.10.33, including stale current-release test assertions.

## Routes
- `/api/effectiveness/open-discovery-discrimination`
- `/api/effectiveness/open-discovery-clusters?limit=500`
- optional classification: `MISSED_OPPORTUNITY` or `PROTECTIVE_ABSTENTION`

## Validation
- Focused 69.10.30–69.10.33: 21 passed, 0 failed.
- Complete `tests/test_apex_69_10_*.py`: 209 passed, 0 failed.
- Python compile: passed for new modules and app integration.
- Full repository pytest could not collect in this sandbox because Flask is not installed (68 collection errors); no functional test failures were observed before collection stopped.
