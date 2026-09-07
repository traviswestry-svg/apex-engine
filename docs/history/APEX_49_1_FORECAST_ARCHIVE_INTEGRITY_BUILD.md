# APEX 49.1 — Forecast Archive Integrity

## Purpose
Ensure every Evening Recap compares the completed session with the forecast that was actually available first, rather than a later regenerated brief.

## Changes
- The first Morning Brief generated for each session is automatically archived as the immutable official forecast.
- Later refreshes are retained in a revision ledger and cannot overwrite the official forecast.
- Morning Brief API responses include archive status, official/revision identity, and revision count.
- Added `/api/morning-brief/archive-status?date=YYYY-MM-DD`.
- Evening Recap missing-forecast responses now explain exactly how the next session becomes eligible.
- Mobile UI confirms when the official forecast is archived and when later revisions are saved.

## Persistence
Set `APEX_GOVERNANCE_DB=/data/apex_governance.db` on Render and attach a persistent disk at `/data`. Without a persistent disk, archives can be lost during restart or deployment.

## Changed files
- `app.py`
- `engine/evening_recap.py`
- `templates/execution_os.html`
- `tests/test_evening_recap_apex49.py`
- `APEX_49_1_FORECAST_ARCHIVE_INTEGRITY_BUILD.md`
