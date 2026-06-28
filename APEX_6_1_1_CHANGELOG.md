# APEX 6.1.1 — Server Confidence Timeline

## Focus
Make the Confidence Timeline useful beyond the current browser session.

## Changed
- Added server-side ICI/decision timeline memory.
- Added `/api/confidence_timeline?ticker=SPX`.
- Added `/api/confidence_timeline/reset?ticker=SPX`.
- Institutional OS now pulls timeline snapshots from the server.
- Timeline rows now include ICI, decision state, net flow, gamma regime, price, and session.
- Added Reset button to the Confidence Timeline card.
- Updated version to `6.1.1_SERVER_CONFIDENCE_TIMELINE`.

## Verify
1. Open `/apex_os`.
2. Confirm Confidence Timeline says server timeline after first refresh.
3. Open `/api/confidence_timeline?ticker=SPX` and verify points accumulate.
4. Click Reset and confirm `/api/confidence_timeline?ticker=SPX` clears.
5. Refresh the browser and confirm the timeline persists server-side until reset/restart.

## Known Limitation
Timeline is in-memory for this sprint. It persists through page refreshes, but not Render restarts. A database-backed replay store should be added in a later replay/review sprint.
