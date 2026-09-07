# APEX 45.2 — Morning Brief Expected Move Feed Fix

## Changed file
- `app.py`

## Fix
The `/api/morning-brief` route now fetches the nearest unexpired SPX option expiration from Polygon/Massive, retrieves near-the-money calls and puts, normalizes the option snapshots, calculates the ATM straddle and average ATM implied volatility, and passes those inputs into the Daily Key Levels engine.

The route also calculates expiration-aware time remaining. After the cash close it skips the expired same-day contract and selects the next valid SPX expiration instead of using zero time remaining.

## Response diagnostics
The endpoint now includes an `options_feed` object with:
- source
- selected expiration
- number of normalized call and put contracts
- status
- error details when unavailable

## Deployment
Replace the repository-root `app.py`, commit to GitHub, and redeploy Render. Then use the Morning Brief refresh control or request `/api/morning-brief?refresh=1` once to bypass any same-session cached brief.

## Required environment variable
- `POLYGON_API_KEY` must be set in Render and the Polygon/Massive subscription must include SPX option snapshots.
