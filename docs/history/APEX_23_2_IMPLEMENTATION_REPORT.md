# APEX 23.2 — Institutional Forecast Engine

Release identity: `16.2.0_INSTITUTIONAL_FORECAST_ENGINE`

## Scope

APEX 23.2 adds a read-only, regime-aware probabilistic forecast layer above the Institutional Trading Brain and Regime Intelligence. It publishes normalized bull, bear, and balance scenario probabilities; projected conditional paths; target zones; uncertainty bands; timing guidance; explicit invalidations; quality disclosures; and Mission Control visibility.

## Safety

The engine cannot place, preview, modify, or authorize broker orders. It does not mutate production weights or risk limits. Existing confirmation, kill-switch, and execution governance remain authoritative.

## New endpoints

- `/api/institutional-forecast/status`
- `/api/institutional-forecast/diagnostics`
- `/api/institutional-forecast/paths`
- `/api/institutional-forecast/bands`
- `/api/institutional-forecast/timing`

## Data honesty

When live price or volatility context is unavailable, the engine reports `LIMITED` and identifies the missing live-price requirement. Forecasts are conditional distributions, not guaranteed price predictions.
