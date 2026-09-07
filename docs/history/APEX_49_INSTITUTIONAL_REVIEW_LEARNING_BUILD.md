# APEX 49 — Institutional Review & Learning System

## Purpose
APEX 49 closes the decision-quality loop by persisting each Morning Brief and comparing its deterministic projections with the completed SPX regular session.

## Implemented
- Persistent Morning Brief evidence snapshots in the governance database.
- `GET /api/evening-recap` with date and refresh controls.
- `GET /api/evening-recap/history` for rolling validation history.
- Deterministic completed-session OHLC, range, direction, and close-location calculations.
- Expected-move containment and magnitude validation.
- Morning projected-regime extraction and actual-regime classification.
- Key-level touch, test count, first-touch, acceptance, and rejection analysis.
- Evidence-only Anthropic narrative that cannot change deterministic scores or prices.
- Evening Recap panel on the Morning Readiness dashboard.
- Honest missing-data behavior: no session bars or Morning Brief produces an explicit unavailable state rather than a fabricated grade.

## API
### `/api/evening-recap`
Optional query parameters:
- `date=YYYY-MM-DD`
- `refresh=1`
- `ticker=SPX`

### `/api/evening-recap/history`
Optional query parameter:
- `limit=30`

## Persistence
Tables are created automatically in `APEX_GOVERNANCE_DB`:
- `apex49_morning_snapshots`
- `apex49_evening_recaps`

For Render persistence across deploys, `APEX_GOVERNANCE_DB` should point to the mounted persistent disk, such as `/data/apex_governance.db`.

## Validation
- Python compilation: PASS
- APEX 49 focused tests: 3 passed
