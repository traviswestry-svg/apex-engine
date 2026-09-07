# APEX Institutional OS 6.0.7A

## Focus
Restore manual scan access after the `/` route was redirected to `/apex_os`.

## Changes
- Added `/scanner` route for the legacy scanner dashboard.
- Updated Institutional OS navigation so **Scanner** opens `/scanner` instead of redirecting back to `/apex_os`.
- Added **Run Scan** button directly on `/apex_os`.
- Added frontend scanner status text for running, complete, and failed scan states.
- Wired the button to `POST /api/run`.
- Updated visible OS build label to `6.0.7_FLOW2_STORY`.

## Files Changed
- `app.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`
- `static/css/apex_os.css`
