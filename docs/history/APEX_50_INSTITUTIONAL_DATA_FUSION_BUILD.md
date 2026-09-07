# APEX 50 — Institutional Data Fusion Engine

## Implemented
- Added a typed data registry with source, confidence, fallback and missing-reason evidence.
- Added `/api/data-quality` and an Institutional Data Quality card on Morning Readiness.
- Wired Massive/Polygon Futures ES Globex bars into the Morning Brief overnight levels.
- Added provider-level completeness scoring for Polygon, Massive, QuantData, TradingView and Benzinga configuration.
- Expanded QuantData gamma aliases for high-gamma, low-gamma and volatility-trigger fields.
- Added explicit Expected Move diagnostics instead of treating every missing value as an unspecified subscription problem.

## Safety behavior
APEX still does not fabricate unavailable values. Missing values remain unavailable, but APEX 50 now records the exact provider and reason.

## Changed files
- `app.py`
- `engine/data_registry.py`
- `engine/data_quality.py`
- `engine/daily_key_levels_adapters.py`
- `templates/execution_os.html`
- `tests/test_apex50_data_fusion.py`
