# APEX 24.4 Validation Report

## Test execution

- New APEX 24.4 tests: 10 passed (`tests/test_institutional_multi_timeframe_v244.py`).
- Complete authoritative `tests/` suite: **1,088 passed, 0 failed**
  (1,078 before APEX 24.4).

## Boot + route verification

Startup printed:
`APEX 24.4 Multi-Timeframe Intelligence routes registered (3 canonical routes verified).`

Endpoint smoke (HTTP status):
- 200 `GET /api/multi-timeframe/status`
- 200 `GET /api/multi-timeframe/alignment`
- 200 `GET /api/multi-timeframe/conflicts`

## Correctness (tested)

- All-bullish across eight timeframes: dominant bias BULLISH, alignment score
  100%, trend agreement 100%, lower-timeframe confirmation true.
- HTF bullish / LTF bearish: higher-timeframe bias dominates the net
  (weight-weighted), lower-timeframe confirmation false, and an HTF_LTF_CONFLICT
  is raised.
- No data -> NEUTRAL, alignment score 0, no available timeframes.
- Alias parsing (weekly/daily/1h) resolves to canonical W/D/1H.

## Migration

None. This engine is stateless (no tables, no persistence).
