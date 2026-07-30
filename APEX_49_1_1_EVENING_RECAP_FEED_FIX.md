# APEX 49.1.1 — Evening Recap Session Feed Fix

## Root cause
The Evening Recap already used the same Polygon aggregate provider as the Morning Brief, but requested a 21-day, one-minute window with a 5,000-row cap. With ascending results, that window could exceed 5,000 bars and truncate the newest session, causing the recap to report that completed-session bars were unavailable.

## Fix
- Added `get_intraday_bars_for_date()` using the canonical `polygon_bar_ticker()` mapping and existing `safe_get_json()` provider path.
- The Evening Recap now requests exactly the selected session date.
- Preserved `I:SPX` mapping, one-minute bars, adjusted results, and fail-closed behavior.
- No new API key or provider is required.

## Changed files
- `app.py`

## Validation
- `python -m py_compile app.py`: PASS
- ZIP integrity: PASS

## Deployment
Replace `app.py` at the repository root and redeploy Render. Then regenerate the recap with `refresh=1`.
