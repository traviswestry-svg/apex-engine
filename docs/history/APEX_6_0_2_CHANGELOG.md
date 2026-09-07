# APEX Institutional OS 6.0.2

## Focus
Professional chart engine and frontend structure migration.

## Major Changes

### Frontend Extraction
- Migrated embedded Flask `render_template_string()` dashboard pages into standard Flask templates.
- Added `templates/dashboard.html`.
- Added `templates/flow.html`.
- Added `templates/assistant.html`.
- Added `templates/apex_os.html`.
- Replaced the old embedded chart page with `templates/chart.html`.

### Lightweight Charts™ Engine
- Added TradingView Lightweight Charts™ via CDN on `/chart`.
- Added true candlestick rendering.
- Added EMA8, EMA21, and VWAP line series.
- Added mouse-wheel zoom.
- Added drag-to-pan.
- Added crosshair OHLC hover display.
- Added Fit Latest, Fit All, Reset, timeframe, and day controls.
- Added viewport preservation across refreshes.
- Added synchronized ES/SPX time axis.

### Modular Static Frontend
Added:

- `static/js/chart_engine.js`
- `static/js/chart_sync.js`
- `static/js/overlays.js`
- `static/js/crosshair.js`
- `static/js/viewport.js`
- `static/css/charts.css`

### Chart Data API
Added:

- `GET /api/charts/state`

This endpoint converts existing APEX chart data into a Lightweight Charts-compatible contract:

```json
{
  "ok": true,
  "charts": {
    "ES": { "candles": [] },
    "SPX": { "candles": [], "levels": {} }
  },
  "market_state": {}
}
```

### Institutional Overlays
The SPX chart now supports price-line overlays for:

- Call Wall
- Put Wall
- Active Gamma Flip
- VWAP
- HVBO Low / High
- Support / Resistance
- Raw Zero Gamma only when Dev Mode is enabled

### ES/SPX Separation
- ES panel uses ES futures data when available.
- If ES futures are unavailable, the panel clearly reports fallback status through the market-state contract.
- SPX panel remains the cash/gamma anchor.
- ES/SPX basis continues to be invalid when true ES futures are unavailable.

## Files Changed

- `app.py`
- `templates/dashboard.html`
- `templates/flow.html`
- `templates/assistant.html`
- `templates/apex_os.html`
- `templates/chart.html`
- `static/js/chart_engine.js`
- `static/js/chart_sync.js`
- `static/js/overlays.js`
- `static/js/crosshair.js`
- `static/js/viewport.js`
- `static/css/charts.css`
- `APEX_6_0_2_CHANGELOG.md`

## Verification

Run:

```bash
python -m py_compile app.py apex_engines.py engine/*.py
```

Then deploy and check:

- `/chart`
- `/api/charts/state?tf=5&days=1`
- `/api/market_state`
- `/api/diagnostics/gamma?ticker=SPX`
- `/`
- `/flow`
- `/assistant`
- `/apex_os`

## Known Limitations

- Lightweight Charts™ is loaded from CDN for simple Render deployment.
- ES futures display depends on Polygon futures availability; if unavailable, APEX labels the fallback instead of showing fake basis.
- Raw zero gamma is hidden from the main chart unless Dev Mode is enabled.
