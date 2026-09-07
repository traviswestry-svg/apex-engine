# APEX 7.6.1 — Empty-tab investigation (Story · Tape · Replay · Signal Log)

Reported: those four tabs never populate on `/apex_os`. Findings below; each was
verified against the code, not assumed.

**Not a DOM/template regression.** The 7.6.0 panels were checked first: the
original `apex_os.html` carries the same `<div>` balance (+1) as the edited one
(434/433 → 450/449), so the added bands are balanced and did not nest the later
tab panes. Story's DOM ids (`execSummary`, `storyMeta`, `storyKnows`,
`storyRecommends`, `narrativeBlock`) all match what `renderStory()` targets, and
every endpoint behind the four tabs returns `200 / ok:true`. The tabs are empty
because of **data and wiring**, not broken markup.

## 1. Signal Log — REAL BUG, fixed here
`/tv_signal` wrote each signal to **both** `SCANNER_STATE["signal_log"]`
(in-memory, last 50) **and** the durable `pine_signals` table — the code comment
even reads *"survives restarts"*. But `/api/signal_log` served **only** the
in-memory list, which is initialised to `[]` on every boot and never hydrated
from disk. So every deploy/restart blanked the Pine Signal Log while the data sat
safely in SQLite.

Fix: `signal_evaluator.recent_signals(limit)` reads the durable table newest-first,
shaped to match the in-memory entries (`received_at` preserved verbatim — it is the
join key the auto-marker patches on), and `app.py` rehydrates
`SCANNER_STATE["signal_log"]` from it at startup. Non-fatal: a read failure logs
and leaves the log empty rather than blocking boot.

Verified: two webhooks → `count = 2`; fresh interpreter, same DB → **was `0`, now
`2`**, outcomes and ICI intact. Covered by `tests/test_signal_log_rehydrate.py`
(5 tests).

Honest limitation: the scoring table persists the decision-relevant subset, so
display-only fields it never stored (`vwap`, `bar_time`, `signal_num`,
`intern_score`, `apex_acceptance`, `apex_poc_migration`) come back `None` on
rehydrated rows. Rows carry `hydrated: true`. A partially-populated log beats an
empty tab, and the outcome data — the part that matters for review — is complete.

## 2. Replay — root-caused; fixed by 7.6.0's headless composition
`_record_replay_frame()`'s docstring claims *"Called by the background scanner on
each cycle"*. It is not: its only call site is inside `api_institutional_os()`.
Frames were therefore recorded **only while a dashboard was open**, which is why
Replay had little or nothing to show. 7.6.0's `compose_institutional_os_headless`
makes that docstring true — the scanner now drives the route every cycle during
`MARKET_OPEN`/`PREMARKET`, so frames record with no browser open. Historical
frames from before this ship do not exist and cannot be backfilled; Replay
populates from the next live session forward.

## 3. Tape — configuration, not code
`/api/flow_tape` returns `status: "NOT_CONFIGURED"` with an empty `rows[]` when
`QUANTDATA_API_KEY` is unset or `ORDER_FLOW_ENABLED` is false. `render.yaml`
declares `QUANTDATA_API_KEY` as `sync: false` (set by hand in the Render
dashboard), so it can be missing on the service even though the repo looks
correct. `ORDER_FLOW_ENABLED` defaults to `true` and is not declared.
Check `/api/flow_tape?tickers=SPX` — `NOT_CONFIGURED` means the key is missing;
`ok:true` with `rows: []` means the key works and the premium filter
(`min_premium`, default from `FLOW_TAPE_DEFAULT_MIN_PREMIUM`) simply matched
nothing.

## 4. Story — wiring verified, needs a live payload to confirm
The Story tab is **not** fed by `/api/story` (the dashboard never calls it —
grep count 0). `renderStory(d)` reads `d.story` from the `/api/institutional_os`
payload. Both the nine-engine pipeline and the 4.5 fallback emit a `story` key,
and every target id exists. So the wiring is sound and the remaining candidates
are payload-side (an empty `story` object, or the pipeline erroring into a
fallback). Confirm on the live service with `/api/institutional_os?ticker=SPX`
and inspect `story` / `engine_mode`.
