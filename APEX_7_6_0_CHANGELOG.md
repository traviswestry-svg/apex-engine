# APEX 7.6.0 — Institutional Premium Strategy Engine

**What shipped.** A native subsystem that turns APEX from a *direction*
generator into a *structure* decision engine. On top of the existing CALL/PUT
read, it now answers **how the market should be traded** — buy premium, sell
premium, or stand aside — and recommends one of:

`DEBIT_CALL_SPREAD` · `DEBIT_PUT_SPREAD` · `BULL_PUT_CREDIT_SPREAD` ·
`BEAR_CALL_CREDIT_SPREAD` · `IRON_CONDOR` · `NO_TRADE`

…complete with modeled strikes, probability, risk, an exit plan, and a
plain-English story of why.

## Design — a read-only consumer of the bus (not a new app)
Per `ARCHITECTURE.md §1`, the engine is a **read-only assembler**. It consumes
the already-composed `STATE["last_result"]` plus the existing `confluence` and
`event_calendar` outputs and **recomputes nothing** — no re-derivation of gamma,
flow, auction, VIX, expected move, or trend. It mirrors the pattern of
`confluence.py` / `decision_intelligence.py` exactly:

- `engine/premium_strategy.py` — the structure-selection engine.
- `engine/premium_strategy_routes.py` — the API + change-alert + scorecard.
- Wired into `app.py` with the same non-fatal `*_AVAILABLE` guard and
  `last_result_provider` closure as the 7.5 engines.

## The decision tree
1. **Strong direction + momentum + confidence** → debit spread (buy premium).
2. **Directional but no high-probability big move** → credit spread in the
   direction (sell premium / theta).
3. **Balanced auction + dealer pinning + elevated vol** → iron condor.
4. **Contradiction / weak trend / event day** → no trade.

**VIX strategy filter** re-expresses direction as debit vs credit: VIX < 16
favours buying premium; VIX > 20 favours selling premium *unless the trend is
elite* (A+ confluence + high momentum + trend-day auction), which keeps debit
spreads allowed. A high-impact **event day gates to NO_TRADE**.

## Strike + pricing model (honest by construction)
The canonical bus carries **expected move** and the **gamma walls**, not a live
per-strike quote. So:
- Short strikes are placed ~1σ OTM (≈16-delta, the credit-spread target),
  bounded to [0.8σ, 1.2σ], and may tuck just beyond a *nearer* gamma wall.
- POP / credit / debit are **modeled** with a normal-distribution approximation
  (`expected_move ≈ 1σ`) and every pricing field is stamped
  `pricing_basis: "modeled_from_expected_move"`. Live-chain pricing supersedes
  at execution — the model exists so the recommendation is complete and
  testable, not a fabricated fill.

**Credit-quality filter** rejects thin credit, poor reward/risk, a short strike
inside the expected move, a gamma wall inside the spread, imminent catalysts, or
sub-floor POP — downgrading to `NO_TRADE` with the reasons. The POP floor
applies to *credit* structures only; debit spreads are directional (~50% POP by
nature) and are judged on thesis + reward/risk instead.

## Opening-range credit model (session-range proxy)
APEX does not publish a formal 15-min opening range or an EMA9/EMA20 stack on
the bus, so the master-prompt Opening-Range model is expressed on **canonical
data**: the developing **session range** as the OR proxy, with the VWAP / POC /
auction / flow reads substituting for the EMA-stack conditions. Flagged
`basis: "session_range_proxy"` so it is never mistaken for a true OR breakout.
When it confirms and agrees with the chosen credit direction, it nudges
confidence up.

## Surfaces
- **`GET /api/premium_strategy`** — the recommendation payload (strategy,
  confidence, legs, exit plan, story, opening-range model, and a `changed`/
  `alert` block when the structure flips).
- **`GET /api/premium_strategy/scorecard`** — recommendations aggregated by
  strategy and by VIX regime, with **realized win-rate and net P&L** per bucket.
  Counts are live immediately; win-rate and P&L populate as the scanner grades
  outcomes at each session's close. Surfaced on the dashboard as the **Premium
  Strategy Scorecard** card at the top of the **Signal Log** tab (`/apex_os`),
  next to the existing Pine signal log — the natural home for realized
  performance. It shows two tables (By Structure / By VIX Regime) answering the
  question the engine exists to settle: *do my credit spreads actually pay in
  high vol, and do my debit spreads pay in low vol?*

  Three deliberate UI choices: `NO_TRADE` rows are excluded from the structure
  table (there is no position to settle) and reported separately as a
  stand-aside count; ungraded buckets render as `—` rather than a misleading
  `0%`; and while fewer than 20 outcomes are graded, the card shows an explicit
  **small-sample warning** — a 100% win rate off one trade is noise, and the
  panel says so instead of flattering the engine.
- **Dashboard** (`templates/apex_os.html`) — a self-contained "Institutional
  Premium Strategy" band (isolated `<style>` + IIFE), so it cannot break the
  main `apex_os.js` poller.
- **Trade Command** (`templates/trade_command.html`) — a "BEST TRADE TODAY"
  card driven by the same endpoint.

## Alerts — wired to the composition cycle
The master prompt asks for alerts **only when the recommendation changes**, and a
read-only GET polled every 20s must not fire notifications. So dispatch runs on
the **server-side `/api/institutional_os` cycle** — the same place the existing
ENTER-NOW alert fires — via `dispatch_and_log(...)`. On each recomposition it
rebuilds the structure and, only when it differs from the last dispatched
structure for that session, **logs the recommendation and sends Telegram**
through the app's existing `send_telegram`. De-dupe is scoped to
`(session_date, ticker)` and re-arms each session, so one alert per genuine flip
per day, independent of dashboard polling. A flip **to** stand-aside is silent
(logged, not alerted). Logging happens on every change regardless of whether
Telegram is enabled, so the scorecard fills even with alerts off. The GET still
returns a `changed`/`alert` block, but purely as a UI hint — it no longer
writes to the log.

## Persistence + outcome grading (wired)
Runtime-created table `premium_recommendations` (under `DB_PATH`) logs each
distinct recommendation with strategy, kind, confidence, VIX/regime, case, POP,
the entry **spot**, the **session date**, and the full **legs** (JSON) needed to
settle it later. Older tables are migrated in place (`ALTER TABLE ADD COLUMN`).

`grade_due_recommendations(get_intraday_bars, now_et)` runs in `scanner_loop`
right beside `signal_evaluator.mark_due_signals`, reusing the **same injected
SPX bar-sampling spine**. Once a structure's 0DTE session has closed, it settles
each leg's intrinsic value at the cash-close print, nets it against the entry
credit/debit, and writes `outcome` (WIN/LOSS/SCRATCH) + realized `outcome_pnl`
($/contract) + an `outcome_notes` audit string. `NO_TRADE` rows settle as
SCRATCH (no position). A session with no bars yet is left for a later pass unless
it is >2 days stale — mirroring the directional grader's data-gap handling.

## Tests
`tests/test_premium_strategy.py` — 17 tests covering each decision-tree case,
the VIX filter (incl. elite-trend override), the credit-quality filter, the
debit-vs-credit POP handling, the exit plan, the opening-range proxy, and the
never-raise safety envelope — plus **11 spine tests**: per-structure settlement
math, the readiness gate, NO_TRADE→SCRATCH, missing-bar retry, and dispatch
de-dupe/silence. Full suite: **199 tests** (run `pytest`, not `pytest tests/`).

## Headless bus composition — alerts without a dashboard
Previously `STATE["last_result"]` only recomposed when the dashboard polled
`/api/institutional_os`, so with no browser open, nothing refreshed and no alert
could fire. The scanner now keeps the bus warm itself: each `scanner_loop` cycle,
during actionable sessions, it calls `compose_institutional_os_headless(...)`,
which drives the **exact same route** via a Flask test request context — no second
composition path to drift out of sync. The route's in-progress guard means that
if a dashboard *is* open concurrently, one caller sees the other and returns stale
instead of double-composing, and the premium alert de-dupe (`_LAST_DISPATCH`,
shared) guarantees a single alert per structure change regardless of who composed.

Gating and cadence are configurable:
`COMPOSE_IOS_IN_SCANNER` (default on), `IOS_COMPOSE_SESSIONS` (default
`MARKET_OPEN,PREMARKET` — off overnight/closed to conserve API calls), and the
cadence follows `SCAN_INTERVAL_SECONDS` (default 300s). Requires the background
scanner to be running (`RUN_SCANNER_ON_IMPORT=true`, as the Render service
already sets).

**ENTER-NOW de-dupe (necessary companion).** The existing directional ENTER-NOW
Telegram alert had no de-dupe, so it fired on every composition — harmless-ish at
dashboard cadence, but headless composition would repeat it every cycle. It now
fires once per distinct recommendation per session via the same `SENT_ALERTS`
pattern `maybe_alert()` uses, with a send-failure retry. This also removes the
pre-existing rapid-repeat behavior when a dashboard polled during a sustained
ENTER-NOW.

## No regressions — and a pre-existing test-suite finding
Pre-existing failures in the shipped tree are untouched by this change and fail
identically with these files removed. 7.6.0 adds 28 passing tests and zero new
failures.

**Two of those failures are date-dependent, not permanent.** While building this
release the suite went from `4 failed / 195 passed` to `2 failed / 197 passed`
with no relevant code change. Cause: `tests/test_decision_intelligence.py` calls
the **live** `build_event_intelligence()`, so on a high-impact event day the
decision engine's event gate correctly suppresses the trade verdict and
`test_complete_setup_trades` / `test_chop_avoids` fail. On 2026-07-14 (CPI) they
failed; on 2026-07-15 (calendar CLEAR) they pass. The engine is behaving
correctly — the *tests* are non-deterministic because they read a live feed
instead of injecting a fixture.

Genuinely permanent failures: the `director` manual-position test and the
`contracts.py`/`persistence.py` architecture-duplicate guard.

Recommended follow-up (not done here, out of scope): pass an explicit
`events={...}` fixture in those two tests, exactly as
`tests/test_premium_strategy.py` does, so the suite stops depending on what day
it is run.
