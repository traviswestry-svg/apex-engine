# APEX 6.2.2 Frontend Route Stability Patch

## Fixes
- Updated visible version labels to `6.2.2_FRONTEND_ROUTE_STABILITY`.
- Added cache-busting query strings to dashboard/chart JS and CSS assets.
- Added no-cache headers for dashboard/API routes to prevent stale Render/browser assets.
- `/` remains redirected to `/apex_os`.
- Chart page Scanner nav points to `/scanner`.
- `/apex_os` now falls back to `heatmap=0` if `heatmap=1` fails.
- Added visible dashboard/chart API error messaging instead of silent loading placeholders.

## Verify
- `/` redirects to `/apex_os`
- `/apex_os` displays `6.2.2_FRONTEND_ROUTE_STABILITY`
- `/chart` displays current version and loads cache-busted JS/CSS
- `/health` reports `mode: 6.2.2_FRONTEND_ROUTE_STABILITY`
- `/api/institutional_os?ticker=SPX&heatmap=1` still works; if heatmap fails, UI loads fallback.
