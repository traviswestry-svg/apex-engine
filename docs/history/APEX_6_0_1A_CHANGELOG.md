# APEX Institutional OS 6.0.1A

## Focus
Finalize 6.0.1 before moving to 6.0.2: Gamma Flip handling, diagnostics, and ES/SPX separation correctness.

## Changes

### Gamma / Zero Gamma
- Preserves QuantData full-curve zero gamma as `raw_zero_gamma`.
- Adds `active_gamma_flip`, a local/tradable gamma reference around current SPX spot.
- Dashboard-facing `zero_gamma` now uses `active_gamma_flip` when available.
- Diagnostics expose the selection method, confidence, crossing counts, local band, and nearest crossings.
- Adds quality flags:
  - `RAW_ZERO_GAMMA_FAR_FROM_SPOT_SOURCE_CONFIRMED`
  - `ACTIVE_GAMMA_FLIP_USED_FOR_DASHBOARD`
  - `ACTIVE_GAMMA_FLIP_LOW_CONFIDENCE`

### ES / SPX Separation
- Data Bus no longer reports ES/SPX basis as `FLAT` when ES futures are unavailable.
- If ES futures data falls back to SPX, basis becomes invalid with label `ES_UNAVAILABLE`.
- ES instrument now reports `isFutures` and `dataAvailable` in `/api/market_state`.

### API Contract
- `/api/market_state` includes:
  - `gamma.zero_gamma`
  - `gamma.active_gamma_flip`
  - `gamma.raw_zero_gamma`
  - `gamma.zero_gamma_method`
  - `gamma.zero_gamma_confidence`
- `/api/diagnostics/gamma` includes the same fields.

## Files Changed
- `app.py`
- `engine/gamma.py`
- `engine/data_bus.py`
