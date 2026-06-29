# APEX 6.3.0 — Volume Profile + Auction Engine

## Scope
Sprint 1 of APEX Terminal 1.0: market auction context using Volume Profile / POC.

## Added
- `engine/volume_profile.py`
  - Session profile
  - POC
  - VAH
  - VAL
  - HVN / LVN nodes
  - Real-volume detection
  - Transparent activity-profile fallback for non-volume index bars
- `engine/auction.py`
  - Auction state
  - POC migration
  - Above/below value classification
  - Acceptance / balance narrative
- `/api/volume_profile?ticker=SPX&range=session&tf=5&days=1`
- `/api/auction_state?ticker=SPX&tf=5&days=1`

## Integrated
- `/api/charts/state` now includes:
  - `volume_profile`
  - `auction`
  - SPX chart level overlays for POC / VAH / VAL
- `/api/institutional_os` now attaches:
  - `volume_profile`
  - `auction`
  - `structure.session_poc`
  - `structure.session_vah`
  - `structure.session_val`
  - `ribbon.poc`, `ribbon.vah`, `ribbon.val`, `ribbon.auction_state`, `ribbon.poc_migration`
- Institutional OS now includes an Auction / Volume Profile panel.

## Data Honesty
- True CME DOM is not included.
- SPX index bars normally have zero volume. When that happens, APEX attempts to use SPY volume scaled to the SPX price coordinate system and flags it as `SPY_VOLUME_PROXY_SCALED_TO_SPX`.
- If no proxy volume is available, APEX uses an `ACTIVITY_PROFILE_NO_VOLUME` fallback and flags it.

## Files Changed
- `app.py`
- `engine/__init__.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`
- `static/js/overlays.js`
- `static/css/apex_os.css`

## Files Added
- `engine/volume_profile.py`
- `engine/auction.py`
- `APEX_6_3_0_CHANGELOG.md`
- `APEX_6_3_0_MANIFEST.md`

## Verify
- `/api/volume_profile?ticker=SPX`
- `/api/auction_state?ticker=SPX`
- `/api/charts/state`
- `/api/institutional_os?ticker=SPX&heatmap=1`
- `/apex_os`
