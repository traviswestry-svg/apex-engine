# APEX Institutional OS 6.0.6

## Scope
Routing, version cleanup, market-health diagnostics, and closed-market data handoff fixes.

## Changed Files
- `app.py`
- `apex_engines.py`
- `APEX_6_0_6_CHANGELOG.md`
- `APEX_6_0_6_MANIFEST.md`

## Fixes
- `/` now redirects to `/apex_os` so the old 3.x scanner dashboard is no longer the default landing page.
- Unified reported app version as `6.0.6_ROUTE_VERSION_HEALTH_PATCH`.
- Added `/api/market_health` to distinguish normal closed-market waits from true data problems.
- Moved direct `python app.py` startup block to the end of the file so all routes are registered before the server starts.
- Added centralized Polygon bar ticker mapping so SPX historical bars use `I:SPX` for institutional OS engines.
- Risk engine price handoff fixed by carrying `stock_price`, gamma walls, and zero gamma through Flow Intelligence.
- Institutional OS endpoint forces the top-level response `version` to the current app version.

## Verify
After deploy, check:

```text
/health
/api/market_health
/apex_os
/chart
/api/charts/state
/api/institutional_os?ticker=SPX&heatmap=0
/api/institutional_os?ticker=SPX&heatmap=1
```

## Notes
Closed-market values such as opening range, fresh Pine execution, session POC, and live session structure may still be unavailable until the cash session opens. `/api/market_health` will label those as `WAITING_FOR_SESSION` instead of treating them as fatal errors.
