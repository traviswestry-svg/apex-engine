# APEX 65.6.2 — Morning Brief Null-Safety Hotfix

## Objective
Eliminate the production HTTP 500 on `/api/morning-brief` when closed/weekend sessions provide `None` for optional expected-move inputs.

## Production symptom
Dashboard displayed:

`Brief failed: TypeError: float() argument must be a string or a real number, not 'NoneType'`

Direct reproduction from the deployed repository produced a related deterministic-layer failure when `straddle=None`:

`TypeError: unsupported operand type(s) for *: 'float' and 'NoneType'`

Both stem from the same contract violation: raw `None` reached the Daily Key Levels core even though that core expects `FEED_REQUIRED` as its sole missing-value sentinel.

## Root cause
`CanonicalMarketDataAdapter.__init__()` stored optional values without normalization:

- spot
- ATM straddle
- ATM IV
- time-to-expiry/time-to-close fraction
- ATR
- ADR

`daily_key_levels.present()` considers every value other than `FEED_REQUIRED` present, so `present(None)` returned true and arithmetic subsequently used `None`.

## Fix
Normalize all optional numeric values with the adapter `_f()` helper at the system boundary. Missing/invalid values become `FEED_REQUIRED`, preserving the no-fabrication contract and allowing deterministic rendering to show `[FEED REQUIRED]` instead of raising.

## Regression coverage
Added `tests/test_apex65_6_2_morning_brief_null_safety.py` covering:

1. `None` optional inputs normalize to `FEED_REQUIRED`.
2. Closed/weekend Morning Brief generation succeeds with no expected-move feed and renders feed-required placeholders.

## Validation
- New 65.6.2 regression tests: 2/2 PASS
- APEX 65.x stabilization tests: PASS
- Repository Python compilation: PASS
- Four legacy APEX 50.3 static template-marker tests remain failing because the current template no longer contains historical marker strings/CSS selectors. They are unrelated to this backend exception and were not modified in this hotfix.

## Behavioral impact
No trading, risk, signal, broker, route, or expected-move calculation behavior changes when valid numeric inputs are present. The only behavior change is missing optional provider values now degrade to `FEED_REQUIRED` rather than throwing.
