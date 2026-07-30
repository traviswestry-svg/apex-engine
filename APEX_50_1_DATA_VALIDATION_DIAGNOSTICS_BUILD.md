# APEX 50.1 — Data Validation & Diagnostics

## Purpose
Raise Morning Brief data completeness without fabricating unavailable market values.

## Implemented
- Expected Move now prefers two-sided ATM mids and uses recent ATM last trades as an explicit MEDIUM-confidence pre-open/closed-market fallback.
- Added Expected Move diagnostics: ATM strike, call/put bid, ask, mid, last, IV, selected method, confidence, and exact failure reason.
- QuantData exposure-by-strike now derives High Gamma Strike and Low Gamma Strike directly from the net-GEX curve.
- Volatility Trigger remains unavailable unless a confirmed local gamma zero crossing exists.
- Gamma Flip, Zero Gamma, and Volatility Trigger are classified NOT_APPLICABLE when the curve has no confirmed local crossing; they no longer reduce completeness.
- ES previous-session close is supplied as an explicit fallback proxy when Massive does not provide official settlement through the aggregate route.
- Data-quality reporting now excludes NOT_APPLICABLE fields from the denominator and separately reports them.

## Changed files
- `app.py`
- `engine/data_registry.py`
- `engine/data_quality.py`
- `engine/daily_key_levels_adapters.py`
- `engine/gamma.py`
- `tests/test_apex50_1_data_validation.py`
- `APEX_50_1_DATA_VALIDATION_DIAGNOSTICS_BUILD.md`

## Validation
- Python compilation: PASS
- APEX 49.2 / 50 / 50.1 focused tests: 9 passed
- ZIP integrity: PASS

## Deployment check
After deployment, regenerate with `/api/morning-brief?refresh=1`. Inspect `options_feed.diagnostics` and `/api/data-quality` for exact provider and fallback evidence.
