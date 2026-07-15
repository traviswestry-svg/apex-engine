# APEX — Architecture Map

> **What this is.** A *descriptive* map of what exists in the codebase right now.
> It is verifiable against the repo — every module, route, and table listed here
> is real as of this writing. It is NOT a plan or a wish-list; forward-looking
> work lives in `BACKLOG.md`.
>
> **Why it exists.** Repeated specs (8.5, 7.5, 8.0) proposed building things that
> already existed, or asserted bugs that were already fixed. This map is the
> antidote: check here *before* specifying or building, so you extend what's
> there instead of duplicating it.
>
> **How to keep it true.** When you add/rename/remove a module, route, or table,
> update the relevant table below in the same change. The architecture test
> (`tests/test_architecture_canonical_imports.py`) guards the canonical import
> paths; this doc is the human-readable companion.

Version constant: `VERSION = "7.6.1_PREMIUM_STRATEGY"` (in `app.py`).
Full test suite: **204 tests** (run with `pytest`, NOT `pytest tests/` — see note
at bottom). Deploy: GitHub file upload → Render. Persistence: SQLite at `DB_PATH`
(mount a Render disk at `/data` and set `DB_PATH=/data/apex_tracking.db` to persist
across deploys).

---

## 1. The Data Bus (the spine)

Everything hangs off one object: **`STATE["last_result"]`**, composed by the
`/api/institutional_os` route (and refreshed each scanner cycle). Feature engines
are *read-only consumers* of this bus — they never re-fetch or recompute what a
prior engine already published. The canonical sub-blocks on the bus:

| Bus key | Produced by | Carries |
|---|---|---|
| `market_state` | `engine/market_state.py` | price, session, auction_state, flow_bias, VIX, etc. |
| `institutional_intelligence` | `engine/institutional_intelligence.py` | the composed institutional read (~43 keys): bias, gamma_regime, pin_probability, flow, ici_score, drivers, momentum, evidence |
| `range_intelligence` | `engine/range_intelligence.py` | projected zones, basis, expansion/reversion/pin probs |
| `overnight_game_plan` | `engine/overnight.py` | ES overnight structure, projected gap, prev-close basis |
| `structure` | `engine/structure.py` | prev_close, key levels |

**Rule for new features:** consume the bus. If you find yourself recomputing
gamma / flow / auction / pin, stop — read it from `institutional_intelligence`.

---

## 2. API Surface (real registered routes)

### Core / composition
`/api/institutional_os` (the composer) · `/api/market_state` · `/api/session` ·
`/api/status` · `/api/v45/status` · `/health` · `/api/market_health` ·
`/api/engine_health` · `/api/nine_engines` · `/api/run` · `/api/mission_control`

### Intelligence engines
`/api/dealer_positioning` · `/api/institutional_intelligence` ·
`/api/auction_intelligence` · `/api/auction_state` · `/api/market_drivers` ·
`/api/strike_magnets` · `/api/flow` · `/api/flow/<ticker>` · `/api/flow_tape` ·
`/api/volume_profile` · `/api/story` · `/api/execution_intelligence` ·
`/api/options_chain_intelligence`

### 7.2–7.5 additions (this session-chain)
`/api/range_intelligence` (+ `/history`, `/scorecard`, `/record_actuals`) ·
`/api/confluence` · `/api/events` · `/api/decision` · `/api/overnight_briefing` ·
`/api/signal_log` · `/api/signal_outcome` · `/api/signal_scorecard`

### 7.6 additions — Premium Strategy Engine
`/api/premium_strategy` (structure selection: debit/credit spread · iron condor ·
no-trade — read-only over the bus) · `/api/premium_strategy/scorecard`

### Active Trade Director (v8.0 director package)
`/api/active_trade_director` (+ `/evaluate`, `/log`, `/reset`, `/scorecard`,
`/timeline`)

### Execution / broker (E*TRADE)
`/api/trade/spx/*` — `chain`, `expirations`, `candles`, `project-levels`,
`recommended-contracts`, `select-contract`, `preview-entry`, `place-entry`,
`preview-change`, `place-change`, `cancel-order`, `active-position`, `flatten`,
`audit-log` · `/api/broker/etrade/status` · `/api/broker/etrade/accounts`

### Ingest / dashboards / replay / review
`/tv_signal` (Pine webhook) · `/apex_os` · `/apex_os/trade_command` · `/assistant`
· `/chart` · `/flow` · `/scanner` · `/dashboard.json` · `/api/replay/session` ·
`/api/replay/frame` · `/api/review/trades` (+ `/trade`, `/summary`) ·
`/api/chart_data` · `/api/heatmap` · `/api/backtest_stats` · `/api/performance` ·
`/api/edge_stats` · `/api/confidence_timeline` (+ `/reset`) · `/api/diagnostics`
(+ `/es_ticker`, `/gamma`)

---

## 3. Engine Modules (canonical paths — post-dedup)

### Top-level `engine/`
Composition & state: `market_state`, `institutional_intelligence`, `data_bus`,
`cache`, `types`, `format`, `math`, `logging`, `diagnostics`, `scheduler`,
`confidence`, `ribbon`.

Intelligence: `dealer_positioning`, `gamma`, `auction`, `auction_intelligence`,
`volume_profile`, `market_drivers`, `rotation`, `strike_magnet`, `flow_intelligence`,
`flow_tape`, `story`, `trend`, `structure`, `market_regime`, `volatility`,
`overnight`, `playbook`, `trade_coach`, `risk`, `execution_intelligence`,
`options_chain`.

7.2–7.5 (this session): `range_intelligence` + `range_routes`, `confluence` +
`confluence_routes`, `event_calendar` + `event_routes`, `decision_intelligence` +
`decision_routes`.

7.6 — Premium Strategy Engine: `premium_strategy` (structure-selection assembler)
+ `premium_strategy_routes`. Read-only consumer of the bus + `confluence` +
`event_calendar`; recomputes nothing. Strikes/POP/credit are modeled from
`range_intelligence.expected_move` + market_state gamma walls (stamped
`pricing_basis: modeled_from_expected_move`). Alerts dispatch from the
`/api/institutional_os` cycle via `dispatch_and_log` (change-deduped per
session, reuses `send_telegram`); outcomes are graded in `scanner_loop` via
`grade_due_recommendations`, which settles each 0DTE structure at cash close
using the same injected `get_intraday_bars` spine as `signal_evaluator`. The
`scanner_loop` also calls `compose_institutional_os_headless(ASSISTANT_TICKER)`
each cycle during actionable sessions (`COMPOSE_IOS_IN_SCANNER` /
`IOS_COMPOSE_SESSIONS`), driving the real `/api/institutional_os` route via a
test request context so the bus stays warm and alerts fire with no dashboard
open — one composition path, guarded against double-compute by the route's
in-progress lock.

Root: `apex_engines.py` (large shared engine library — imported by many
`engine/*.py` shims like `trend.py`, `risk.py`, `structure.py`).

### `engine/director/` — Active Trade Director (v8.0)
`director` (build loop), `persistence` (hysteresis/debounce + **position-truth
override**), `contracts` (state/directive constant sets), `states`, `lifecycle`,
`position`, `thesis`, `hold_level`, `conflict`, `narrative`, `snapshots`, `store`,
`evaluator` (outcome scoring of directives), `routes`.

### `engine/execution/` — order lifecycle (canonical)
`broker_interface`, `trade_risk_guard`, `price_mapper`, `trade_audit`,
`bracket_manager`, `trade_routes`. Broker adapter: `engine/brokers/etrade_adapter`.

### `engine/options/`
`options_data_bus`, `polygon_chain`.

### Signal evaluator (root)
`signal_evaluator.py` — persists Pine signals + auto-scores by SPX MFE/MAE.

---

## 4. Persistence (SQLite tables)

| Table | Written by | Holds |
|---|---|---|
| `apex_signals` | scanner | scan/signal records |
| `director_directives` | director | emitted directives |
| `director_outcomes` | director evaluator | graded directive outcomes |
| `range_projection_history` | range engine | projections for accuracy scoring |
| `replay_snapshots` | replay | minute snapshots |
| `tracked_ideas` | backtest tracking | idea → outcome |
| `trade_reviews` | review | post-trade reviews |
| `pine_signals` | signal_evaluator | Pine signals + MFE/MAE outcomes (created at runtime) |
| `premium_recommendations` | premium_strategy_routes | structure recs (+ spot, session_date, legs JSON); `outcome`/`outcome_pnl` settled at cash close by scanner_loop (created at runtime) |

All read `DB_PATH`. On Render, persist via a mounted disk (`/data`).

---

## 5. Non-fatal module pattern

Every optional engine is imported inside `try/except` with an `*_AVAILABLE` flag
and a route registered only if the import succeeded. A broken feature degrades to
a 404 on its own endpoint and a `... unavailable (non-fatal)` log line — it never
crashes the app. This is why one bad file (e.g. a missing `VERSION` constant)
takes down only its own route, not the dashboard.

---

## 6. Frontend

- `templates/apex_os.html` — main dashboard. New intelligence panels (Range,
  Decision) are **inline self-contained bands** (isolated `<style>` + IIFE) so
  they can't break the main `static/js/apex_os.js` poller and sidestep the
  CSS cache-bust problem.
- `templates/trade_command.html` — separate self-contained Trade Command page
  (own `<style>`), rendered at `/apex_os/trade_command`.
- `static/js/apex_os.js` (~4,450 lines) — main dashboard poller/renderer.
- `static/css/apex_os.css` — shared styles. Cache-busted via
  `?v={{ asset_version }}` where `STATIC_ASSET_VERSION = VERSION.replace(".","_")`.
  **Bump the asset token when you change CSS**, or browsers serve stale styles.

---

## 7. Known conditions & gotchas

- **Run `pytest`, not `pytest tests/`.** The full suite (171) includes nested
  tests under `engine/director/`. `pytest tests/` runs only ~120 and once hid a
  real failing director test. The architecture test enforces no *new* duplicate
  test files, but the historical `engine/director/test_active_trade_director.py`
  still exists — always run full discovery.
- **`engine/execution.py` (module)** coexists with **`engine/execution/` (package)**.
  Left intentionally; don't "clean up" without checking imports — ambiguous but
  currently functional.
- **Event calendar `DATED_EVENTS`** (`engine/event_calendar.py`) is a curated
  2026 table (FOMC/CPI/NFP/PPI). It self-flags `data_stale` past its horizon;
  refresh from BLS/Fed calendars periodically. Rule-derived events (OPEX, quad,
  month/quarter-end) need no upkeep.
- **Outcome data is young.** The learning/calibration surfaces exist but only
  became populated recently; their outputs aren't statistically meaningful until
  weeks of graded outcomes accumulate. See `BACKLOG.md` Tier 2.
