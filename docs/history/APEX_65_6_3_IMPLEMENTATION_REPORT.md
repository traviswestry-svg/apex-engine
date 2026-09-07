# APEX 65.6.3 — Morning Brief Null Contract Hotfix

## Objective
Eliminate the remaining closed-market Morning Brief 500 caused by raw `None` values crossing the Daily Key Levels numeric contract.

## Production failure reproduced
`/api/morning-brief?refresh=1` could fail when optional expected-move inputs were unavailable on a closed/weekend session. A local reproduction with `straddle=None`, `iv=None`, `time_to_close_frac=None`, `atr_val=None`, and `adr_val=None` reached `expected_move()` and attempted arithmetic on `None`.

## Root cause
1. `CanonicalMarketDataAdapter.__init__` retained raw optional values instead of normalizing them through `_f()`.
2. `daily_key_levels.present()` considered every value except `FEED_REQUIRED` to be present, which incorrectly included `None`.

## Changes
- `engine/daily_key_levels.py`
  - `present(None)` now returns `False`.
  - `None` is treated as unavailable data, consistent with the engine's FEED_REQUIRED contract.
- `engine/daily_key_levels_adapters.py`
  - Normalize `spot`, `straddle`, `iv`, `time_to_close_frac`, `atr_val`, and `adr_val` through `_f()` at adapter construction.
- `tests/test_apex65_6_3_morning_brief_null_contract.py`
  - Added regression coverage for the core presence contract, adapter normalization, and a fully-null closed-market deterministic Morning Brief build.

## Validation
- New null-contract regression tests: 3/3 PASS.
- New regression + existing APEX 65.6 Monday-readiness tests: 15/15 PASS.
- Python compile: PASS.

## Behavioral impact
No trading, scoring, risk, execution, or live-market calculations changed. Valid numeric values are preserved. Missing optional values now degrade to `[FEED REQUIRED]` instead of causing a 500.
