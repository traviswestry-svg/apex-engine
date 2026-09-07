# APEX 6.4.0 Changelog — Replay & Post-Trade Analytics

**Sprint:** 6.4.0  
**Date:** 2026-06-28  
**Status:** Production

## New Features

### app.py — Replay & Review endpoints (NEW)

#### GET /api/replay/session?ticker=SPX&date=YYYY-MM-DD
- Returns frame index for a session (in-memory for today, SQLite for historical)
- Each frame: frame_index, frame_time, decision_state, ici, price

#### GET /api/replay/frame?ticker=SPX&date=YYYY-MM-DD&time=HH:MM
- Returns the nearest full APEX snapshot for the requested time
- Includes: decision_state, ici, price, poc, vah/val, auction_state, tape_bias, grade

#### POST /api/review/trade
- Body: ticker, side, entry/exit time+price, contract, pnl, reason_entered/exited,
  followed_plan, mistakes, lesson, screenshot_url
- Persists to SQLite (same DB as tracking)
- Returns id of saved review

#### GET /api/review/trades?ticker=SPX&limit=50
- Returns paginated list of saved trade reviews
- Ordered by most recent

#### GET /api/review/summary?ticker=SPX
- Returns: win_rate, winner_count, loser_count, avg_pnl, avg_win, avg_loss,
  avg_r, followed_plan_pct, top_mistakes, recent_lessons

### Replay Frame Recording
- `_record_replay_frame()` called on each /api/institutional_os load
- In-memory store per session date (capped at 480 frames / ~8 hours at 1-min intervals)
- Best-effort SQLite persistence (non-fatal if disk unavailable)
- Frame snapshot: decision_state, ici, stock_price, poc, vah, val, auction_state, tape_bias

### Database
- `trade_reviews` table: all review fields, auto-timestamp
- `replay_snapshots` table: session_date, frame_time, ticker, snapshot_json
- Both tables added to existing tracking DB (DB_PATH env var)
- Migrations are additive / CREATE IF NOT EXISTS — no data loss
- `_init_review_db()` called at startup, non-fatal on failure

### Frontend

#### templates/apex_os.html — Replay tab (UPGRADED)
- Date picker (HTML date input, defaults to today)
- "Load" button → fetches /api/replay/session, populates scrub bar
- Frame scrubber loads individual frames via /api/replay/frame
- Frame display: decision state, ICI, price, POC, auction state, tape bias, grade

#### templates/apex_os.html — Review tab (UPGRADED)
- Trade Entry Form with all fields
- Performance Summary panel (win rate, avg P&L, avg R, plan adherence)
- Trade History table (30 most recent)
- All DB operations via /api/review/* endpoints

#### static/js/apex_os.js
- `initReviewForm()` — wires the save button and status feedback
- `loadReviewSummary()` — renders win rate, avg R, top mistakes, lessons
- `loadTradeHistory()` — renders trade history table
- `initReplayDatePicker()` — wires date picker + load button
- `loadReplaySession(date)` — fetches session index, updates scrub
- `loadReplayFrame(date, time)` — renders a single replay frame

## Notes
- Render disk: set DB_PATH=/data/apex_tracking.db in dashboard env vars
- Without Render disk: SQLite uses local path (data not persisted across deploys)
- In-memory replay store is reset on server restart
- No external database required — SQLite only
