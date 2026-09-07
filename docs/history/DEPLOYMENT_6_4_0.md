# APEX 6.4.0 Deployment Instructions

## Pre-Deployment Checklist
- [ ] Push to GitHub: `git add -A && git commit -m "APEX 6.4.0 APEX Terminal 1.0" && git push`
- [ ] Render auto-deploys on push (verify in Render dashboard)

## Environment Variables (no new vars required)
All existing env vars carry forward unchanged.

Optional (already documented):
- `DB_PATH` — defaults to `apex_tracking.db` (local) or `/data/apex_tracking.db` (Render disk)
- `REVIEW_DB_PATH` — defaults to `DB_PATH`; override to use separate review database
- `REPLAY_MAX_FRAMES` — max replay frames kept in memory per session (default: 480)

Reminder: Render does NOT auto-sync env vars from render.yaml — set them manually in the dashboard.

## Database Migration
The 6.4.0 startup adds two new tables to the existing DB:
- `trade_reviews`
- `replay_snapshots`

These are created with `CREATE TABLE IF NOT EXISTS` — no existing data is affected.
No manual migration step required.

## Verification Checklist
Run these after deployment:

| Check | URL |
|-------|-----|
| Health | GET /health |
| Main terminal | GET /apex_os |
| Chart terminal | GET /chart |
| Full OS pipeline | GET /api/institutional_os?ticker=SPX&heatmap=1 |
| Volume profile | GET /api/volume_profile?ticker=SPX&range=session |
| Auction state | GET /api/auction_state?ticker=SPX |
| Flow tape | GET /api/flow_tape |
| Confidence timeline | GET /api/confidence_timeline?ticker=SPX |
| Replay session | GET /api/replay/session?ticker=SPX&date=YYYY-MM-DD |
| Review summary | GET /api/review/summary |

## Expected Responses When Market Closed
- /api/volume_profile → `"status": "NO_BARS"` or `"WAITING_FOR_SESSION"`
- /api/flow_tape → `"rows": []` (QuantData returns no intraday rows outside session)
- /api/replay/session → `"frame_count": 0` until first scan cycle completes
- /api/review/summary → `"trade_count": 0` until first trade is logged

## Story Engine 3.0 Behavior
- `[PRE-MARKET]` / `[AFTER-HOURS]` / `[CLOSED SESSION]` prefixes on closed market
- Auction chapter appears only when volume profile is available (`available: true`)
- Flow tape chapter appears only when tape has rows (`row_count > 0`)
- Fallback to apex_engines v2 story if story_v3 raises

## Trade Coach 3.0 Behavior
- Falls back to v2 coach if build_trade_coach_v3 raises
- Checklist readiness score (0–100) requires ICI, execution, tape, and profile
- `invalidation` is computed from POC/VWAP ±2 pts when risk module stop is null
