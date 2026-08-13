# APEX Institutional OS 6.1.0 — Terminal UI Refinement

## Focus
Convert the Institutional OS page from a card-heavy dashboard into a trading-terminal workflow.

## Changes
- Added a primary workflow section above the tabs.
- Moved Scanner Qualified Ideas to the top of the page so completed scans are immediately visible.
- Reworked scanner ideas into a sortable-style terminal table layout instead of buried idea cards.
- Added a large Professional Chart Terminal panel that embeds `/chart` directly inside Institutional OS.
- Added a right-side Command Center with current decision, ICI, SPX price, flow, gamma, and walls.
- Added a Confidence Timeline that tracks ICI and decision-state changes during the session.
- Added a Coach Snapshot beside the chart for fast entry/stop/target context.
- Preserved existing Dashboard, Flow Intelligence, Story, Replay, Review, Run Scan, and Refresh controls.
- Updated version label to `6.1.0_TERMINAL_UI_REFINEMENT`.

## Files Changed
- `app.py`
- `templates/apex_os.html`
- `static/js/apex_os.js`
- `static/css/apex_os.css`

## Verification
1. Open `/apex_os`.
2. Confirm Scanner Qualified Ideas appears near the top.
3. Click `Run Scan` and confirm the ideas table updates.
4. Confirm the embedded chart loads in the main terminal section.
5. Confirm Command Center, Coach Snapshot, and Confidence Timeline populate after `/api/institutional_os` loads.
6. Confirm the older tabs still work.

## Known Limitations
- The embedded chart uses `/chart` in an iframe for this sprint. A future sprint can wire the chart components directly into the Institutional OS DOM if needed.
- The confidence timeline is in-memory and resets on page refresh.
