# APEX 6.2.1 Tab Routing Stabilization

## Fix
- Restored Dashboard, Flow Intelligence, Story Engine, Replay, and Review tab functionality after the 6.2.0 upgrade.
- Fixed `initTabs()` so it only binds buttons with `data-tab`.
- Prevented ticker buttons (`SPX`, `SPY`, `QQQ`, `IWM`) from accidentally deactivating all tab panes.
- Updated the default tab activation to target `data-tab="dashboard"` directly.
- Updated visible/version labels to `6.2.1_TAB_ROUTING_STABILIZATION`.

## Files Changed
- `app.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`

## Verify
1. Open `/apex_os`.
2. Confirm Dashboard is visible by default.
3. Click Flow Intelligence, Story Engine, Replay, and Review.
4. Click SPX/SPY/QQQ/IWM ticker buttons and confirm the active tab remains visible.
5. Confirm Run Scan still works.
