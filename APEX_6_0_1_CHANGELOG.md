# APEX Institutional OS 6.0.1

## Scope
Data Bus, Gamma rewrite, Diagnostics, ES/SPX separation.

## Backend
- Added `engine/` package.
- Added `engine/gamma.py` with raw -> normalized -> engine diagnostics.
- Added `engine/data_bus.py` with a unified `market_state` contract.
- Added `engine/diagnostics.py` trace object.
- Replaced `quantdata_gex_layer()` with the 6.0.1 gamma parser.
- Added `/api/market_state`.
- Added `/api/diagnostics/gamma`.

## Gamma Fix
- SPX compressed levels normalize correctly:
  - `75 -> 7500`
  - `730 -> 7300`
  - `73.54 -> 7354`
  - `660.75 -> 6607.5`
- SPY/QQQ/stock tickers are not scaled.
- Call wall selection is anchored above SPX spot when available.
- Put wall selection is anchored below SPX spot when available.
- Zero gamma is preserved from the source calculation and flagged if far from spot.

## ES/SPX Separation
- ES is treated as futures lead.
- SPX is treated as cash/gamma anchor.
- Dashboard Data Bus ribbon now shows ES, SPX, ES/SPX basis, Call Wall, Put Wall, Zero Gamma.

## Diagnostics
- `/api/diagnostics/gamma?ticker=SPX` returns raw response summary, stock-price normalization, strike examples, engine output, and quality flags.
