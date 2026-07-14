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
  strategy and by VIX regime. Counts + avg-confidence are live now; win-rate
  surfaces populate as `outcome` grades accumulate (consistent with
  `ARCHITECTURE.md §7` — outcome data is young).
- **Dashboard** (`templates/apex_os.html`) — a self-contained "Institutional
  Premium Strategy" band (isolated `<style>` + IIFE), so it cannot break the
  main `apex_os.js` poller.
- **Trade Command** (`templates/trade_command.html`) — a "BEST TRADE TODAY"
  card driven by the same endpoint.

## Alerts
The master prompt asks for alerts **only when the recommendation changes**. The
route tracks the last emitted strategy per ticker and stamps each response with
`changed` + a formatted `alert.text`. It deliberately does **not** dispatch
Telegram itself — a read-only GET polled every 20s must not fire notifications.
The scanner cycle is the correct dispatch point; `alert.text` is the ready-made
payload for it to send.

## Persistence
New runtime-created table `premium_recommendations` (under `DB_PATH`): logs each
distinct recommendation with strategy, kind, confidence, VIX/regime, case, and
POP. The `outcome` column (WIN/LOSS/SCRATCH) is reserved for the grading hook —
intraday option-outcome grading reuses the same price-sampling spine the
directional signal log already uses.

## Tests
`tests/test_premium_strategy.py` — 17 tests covering each decision-tree case,
the VIX filter (incl. elite-trend override), the credit-quality filter, the
debit-vs-credit POP handling, the exit plan, the opening-range proxy, and the
never-raise safety envelope. Full suite: **188 tests** (run `pytest`, not
`pytest tests/`).

## No regressions
The four pre-existing failures in the shipped tree (`director` manual-position
test, the `contracts.py`/`persistence.py` architecture-duplicate guard, and two
`decision_intelligence` verdict tests) are untouched by this change and fail
identically with these files removed. 7.6.0 adds 17 passing tests and zero new
failures.
