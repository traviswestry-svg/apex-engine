# APEX Institutional OS 6.0.8

## Scope
Scanner route stability and scanner results visibility inside Institutional OS.

## Changes
- Fixed `/scanner` route by passing the required `data` object into `templates/dashboard.html`.
- Added `/api/scanner_ideas` compact endpoint for scanner results.
- Added Scanner Qualified Ideas panel inside `/apex_os`.
- Manual Run Scan now refreshes both Institutional OS and scanner ideas.
- Updated version to `6.0.8_SCANNER_RESULTS_PATCH`.

## Verify
- `/scanner` should load without Internal Server Error.
- `/api/scanner_ideas` should return `idea_count` and `ideas`.
- `/apex_os` should show qualified scanner ideas after a completed scan.
