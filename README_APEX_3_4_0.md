# APEX 3.4.0 — Backtest Timing: Phase 1 (Forward Tracking)

This is the foundation for real, evidence-based "how long should I expect to
hold this" stats, replacing guesswork with actual outcomes from this engine's
own signals. It does **not** attempt to reconstruct history retroactively —
see "Why not a retroactive backtest" below for the reasoning.

## What it does

1. **Records every qualified idea once.** The first time a ticker+direction
   setup clears `MIN_FINAL_SCORE`, a row is written to a `tracked_ideas` table
   (SQLite) with its full score breakdown, entry price, T1/T2/stop levels, and
   the option contract picked at the time. If that same ticker+direction is
   still open (unresolved), it won't be logged again on the next scan — one
   row per actual trade idea, not one row per scan cycle.

2. **Resolves trades daily.** Once a day (tracked by calendar date, not scan
   count), `resolve_open_trades()` walks forward through real daily bars
   (`get_daily_bars`, the same Polygon data the rest of the engine uses) for
   every still-open row and checks whether the day's high/low touched T1, T2,
   or the stop first. The conservative rule: if a target and the stop both
   print on the same daily bar, it's counted as the stop, since daily OHLC
   can't tell us which came first intraday — protecting against an inflated
   win rate matters more than flattering it. Trades that haven't resolved
   within `TRACK_MAX_HOLD_DAYS` (default 30) get marked `EXPIRED` and drop out
   of the stats rather than skewing them.

3. **Aggregates by score bucket + direction.** `/api/backtest_stats` groups
   resolved trades into `<78` / `78-84` / `85-89` / `90-100` buckets per
   direction, returning sample size, win rate (T1 or T2 reached vs. stopped
   out), and median trading days to each outcome.

4. **Surfaces on the dashboard.** Each card's Stock Targets section now shows
   a second line under the ATR ballpark: real historical stats for that
   score bucket once `TRACK_MIN_SAMPLE` (default 10) resolved trades exist,
   or an honest "not enough resolved trades yet (n=X)" message before that.

## New environment variables

```text
DB_PATH=/data/apex_tracking.db   # SQLite file -- MUST be on the mounted disk, not /tmp or the repo dir
TRACKING_ENABLED=true            # set false to disable recording/resolution entirely
TRACK_MAX_HOLD_DAYS=30           # trades older than this with no resolution get marked EXPIRED
TRACK_MIN_SAMPLE=10              # minimum resolved trades in a bucket before stats display
```

## Required manual step before this works on Render

`render.yaml` now declares a 1GB persistent disk mounted at `/data`, plus the
env vars above. **This is an existing service, not a new one** — per the
pattern you already know from the futures system, Render does not
auto-apply new disks or env vars to an already-provisioned service from a
`render.yaml` change alone. You'll need to add the disk and these four env
vars manually in the Render dashboard (Settings → Disks, and Environment) for
this service. Without the disk mounted, `DB_PATH=/data/...` will fail to
write and tracking will silently no-op (each write is wrapped in a try/except
that logs and continues rather than crashing scans) -- check Render logs for
`record_idea_if_new error` if `/api/backtest_stats` stays empty indefinitely.

## Why not a retroactive backtest (Approach B)

Re-running the scoring pipeline against historical data would produce usable
numbers immediately instead of waiting months for forward data to
accumulate, which is the obvious appeal. It wasn't built because three open
problems would need solving first, none of which can be resolved without
testing directly against the live APIs:

- **QuantData historical depth is unverified.** The four QuantData layers
  (net-flow, order-flow, dark-flow, dark-pool-levels) all support a session
  date parameter, but it's unconfirmed whether that extends back months for
  arbitrary historical dates the way `get_daily_bars` does, or only covers a
  recent rolling window.
- **Lookahead bias is easy to introduce by accident.** Every score component
  that uses "current" context (regime score, relative strength vs. SPY,
  catalyst news) would need to be recomputed using only information that
  existed as of each historical day, not today's value.
- **The dynamic ticker universe is itself history-dependent.** `get_dynamic_tickers()`
  selects today's biggest movers from yesterday's session. Replaying that
  selection consistently across history is a separate problem from replaying
  the scoring math, and using today's known-good tickers to test the past
  would be survivorship bias.

If forward-tracked sample sizes prove the timing data is valuable, Approach B
becomes worth the investment to backfill faster -- but Phase 1 needed to ship
first to start the clock and to validate that this is worth the larger build
before committing to it.
