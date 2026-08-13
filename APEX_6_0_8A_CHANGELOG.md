# APEX Institutional OS 6.0.8A — Scan Button Stabilization

## Fixes
- Restored the manual **Run Scan** action in the Institutional OS top action bar.
- Added a second **Run Scan** button inside the Scanner Qualified Ideas panel.
- Added **Refresh Ideas** button for scanner results only.
- Restored the Scanner navigation link to `/scanner` instead of redirecting back to `/apex_os`.
- Added scan status text showing idle/running/complete/failure states.
- Added missing `loadScannerIdeas()` implementation so scanner ideas render reliably.
- Added `runManualScan()` handler that calls `POST /api/run`, then refreshes `/api/scanner_ideas` and the OS dashboard.
- Updated version label to `6.0.8A_SCAN_BUTTON_STABILIZATION`.

## Verify
1. Open `/apex_os`.
2. Confirm top-right shows `Run Scan`, `Refresh`, and scanner status.
3. Click `Run Scan`.
4. Confirm button changes to `Scanning...`.
5. Confirm the Scanner Qualified Ideas panel updates after the scan completes.
6. Open `/scanner` and confirm the legacy scanner dashboard still loads.

## Files Changed
- `app.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`
- `static/css/apex_os.css`
