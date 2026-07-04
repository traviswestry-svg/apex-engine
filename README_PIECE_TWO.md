# APEX 8.0 — Piece Two: the signal-outcome spine

The measurement foundation. Every actionable APEX decision is now logged with its
full entry context, then price is sampled each scan to track MFE / MAE and resolve
WIN / LOSS / EXPIRED. **Every statistic it produces comes from a realized outcome —
never an estimate.** This is what makes an honest conviction number (Piece Three)
and the Execution tab's Edge Statistics possible.

## Deploy (3 files, overwrite in place)
```
app.py                    → app.py
templates/apex_os.html    → templates/apex_os.html
static/js/apex_os.js      → static/js/apex_os.js
```
These build cumulatively on the System Mode + four-layer nav work — the frontend
files carry all of it; `app.py` carries System Mode + the spine.

## What it does

### New table: `apex_signals` (separate from tracked_ideas / trade_reviews)
`tracked_ideas` is daily-swing; `trade_reviews` is a manual journal. Neither fits
0DTE. The spine adds an intraday table that logs APEX's own decisions and tracks
them by sampling price on every scan.

### Logging — `log_apex_signal()`
A signal is written the first time a ticker+direction setup becomes **actionable**:
- there is a directional side (CALL/PUT) with a valid stop and target1, and
- the execution stage has reached at least `SPINE_MIN_STAGE` (default `PREPARE`), and
- the market is open (unless `SPINE_LOG_WHEN_CLOSED=true`).

De-duped against any still-OPEN row for the same ticker+direction, so a setup that
persists scan after scan is logged once, not hundreds of times. Full entry context
is captured: entry/stop/T1/T2, risk points, contract, stage, Pine-confirmed, ICI,
flow score, conviction, plus a compact context snapshot (gamma regime, auction
state, session type, grade, POC migration, VIX) for pattern memory later.

### Tracking — `update_open_signals()`
On every scan, for each OPEN signal on that ticker:
- updates **MFE** (max favorable excursion) and **MAE** (max adverse), in points and R,
- resolves **WIN** (hit T1/T2), **LOSS** (hit stop), or **EXPIRED** (session close or
  `SPINE_MAX_HOLD_MIN`, default 120m),
- books the exit at the level that was hit and records hold time and realized R.

Sampled resolution caveat (by design): outcomes are checked once per scan, not tick
by tick. If a target and the stop are both crossed between two samples we can't know
which printed first, so we **count the stop** — the spine will never overstate win
rate. (Same conservative philosophy as the existing daily tracker.)

### Both are driven by one non-fatal hook
`_spine_ingest(ticker, result)` runs at the end of each APEX scan (right after
`STATE["last_result"] = result`): it updates open signals first (freeing a resolved
slot), then logs a fresh signal if the current read is actionable. Wrapped so any
error prints and moves on — the scanner is never affected.

### New endpoints
- `GET /api/apex_signals?limit=N&status=OPEN|WIN|LOSS|EXPIRED` — the log plus stats.
- `GET /api/edge_stats?direction=CALL|PUT` — measured edge stats, with a `ready` flag.

`signal_spine_stats()` returns: n_total, n_open, n_resolved, wins, losses, expired,
win_rate (over decided trades, excluding expired), avg_outcome_r, avg_hold_min,
avg_mfe_r, avg_mae_r, and `min_sample_for_confidence` (20). `ready:false` means
"not enough resolved trades yet" — the UI shows pending, never a fabricated number.

### The Execution tab's Edge block is now live
The "AWAITING OUTCOME DATA" placeholder from Piece One is wired to `/api/edge_stats`:
- **No data:** stays pending ("These are measured from realized trades…").
- **Early (< 20):** shows the count with an "EARLY · n=…" tag and a "provisional" note.
- **Enough (≥ 20):** shows win rate, avg hold, avg MAE (R), and sample size with a
  "MEASURED · n=…" tag.

## Configuration (env vars, all optional)
| Var | Default | Meaning |
|-----|---------|---------|
| `SPINE_ENABLED` | `true` | master switch |
| `SPINE_DB_PATH` | `DB_PATH` | where the table lives — set to your `/data` mount to persist across redeploys |
| `SPINE_MIN_STAGE` | `PREPARE` | log once stage ≥ this (`WATCH`<`PREPARE`<`ARMED`<`EXECUTE`) |
| `SPINE_LOG_WHEN_CLOSED` | `false` | log outside RTH (for testing) |
| `SPINE_MAX_HOLD_MIN` | `120` | force-expire signals held longer than this |

**Persistence:** like the other trackers, `SPINE_DB_PATH` defaults to `DB_PATH`. If
you've pointed `DB_PATH` at your Render `/data` disk, the spine persists across
redeploys automatically. If not, it still works but resets on redeploy.

## Verified
- `app.py` compiles; `apex_os.js` passes `node --check`.
- End-to-end: logged a CALL, dup-guarded a repeat, tracked MFE 6.5 / MAE 2.0
  (1.30R / 0.40R), resolved WIN at T1 (1.20R); a PUT hit its stop → LOSS; win rate
  moved 100% → 50%; by-direction split correct (CALL 100 / PUT 0).
- Fresh DB returns `ready:false`, `win_rate:null`, `n_total:0` (honest pending).
- All endpoints return 200; boot smoke test clean with all engines loaded.
- Execution Edge block populates from a measured `/api/edge_stats` response
  (62.5% / 13.5m / 0.61R / n=24, tag "MEASURED · n=24") and stays pending otherwise.

## What it does NOT do (by design)
- No conviction score yet — that's Piece Three, and it will be **calibrated against
  these outcomes**, not asserted from engine agreement. The spine is the prerequisite.
- No pattern memory ("this setup occurred N times") yet — the `context_json` snapshot
  is being captured now precisely so that feature has data to query later.
- It starts empty. It only accumulates during live RTH sessions, so you'll see the
  first rows Monday. Give it a few weeks before the edge stats mean anything — the
  `ready`/`EARLY`/`MEASURED` states are there to keep you honest about that.

## Suggested next
**Piece Three — calibrated conviction + pattern memory**, once the spine has
accumulated a meaningful sample. Conviction becomes a number measured from realized
outcomes; "this setup occurred N times, X% win" queries the `context_json` snapshots.
Or **Piece Four — the Signal Log tab UI**, which turns `/api/apex_signals` into the
"reason / confidence / winner? / max excursion / should-have-entered?" table you
described. Either is a clean next step; the spine feeds both.
