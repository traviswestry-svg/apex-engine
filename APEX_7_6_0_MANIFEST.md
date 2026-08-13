# APEX 7.6.0 — Manifest

Version constant (`app.py`): `VERSION = "7.6.2_PREMIUM_STRATEGY"`
(→ `STATIC_ASSET_VERSION = "7_6_0_PREMIUM_STRATEGY_css2"`, cache-busts the panels).

## New files
| Path | Role |
|---|---|
| `engine/premium_strategy.py` | Structure-selection engine — read-only assembler over the Data Bus. Never recomputes. |
| `engine/premium_strategy_routes.py` | routes + `dispatch_and_log` (cycle alert/log) + `grade_due_recommendations` (cash-close settlement); SQLite logging + migration. |
| `tests/test_premium_strategy.py` | 28 tests — decision tree, VIX filter, quality filter, exit plan, OR proxy, safety + settlement math, readiness gate, NO_TRADE scratch, dispatch de-dupe/silence. |
| `APEX_7_6_0_CHANGELOG.md` | This release's changelog. |
| `APEX_7_6_0_MANIFEST.md` | This file. |
| `APEX_7_6_1_CHANGELOG.md` | 7.6.1 — empty-tab investigation + signal-log rehydrate fix. |
| `APEX_7_6_2_CHANGELOG.md` | 7.6.2 — alerts rewritten as B/S + strike + P/C order tickets. |
| `tests/test_signal_log_rehydrate.py` | 5 tests — durable signal-log read shape, ordering, outcomes, safety. |

## Modified files
| Path | Change |
|---|---|
| `signal_evaluator.py` | Added `recent_signals(limit)` — durable read for the Pine signal log. |
| `app.py` | (0) rehydrate `SCANNER_STATE["signal_log"]` from disk at startup (fixes empty Signal Log after restarts); (1) import guard + `dispatch_and_log`/`grade_due_recommendations`; (2) route registration; (3) `VERSION` bump; (4) `dispatch_and_log(...)` on the `/api/institutional_os` cycle; (5) `grade_due_recommendations(...)` in `scanner_loop`; (6) `compose_institutional_os_headless(...)` helper + gated call in `scanner_loop` so the bus refreshes with no dashboard open; (7) de-dupe on the existing ENTER-NOW alert. All non-fatal. |
| `templates/apex_os.html` | (1) Self-contained "Institutional Premium Strategy" band (band #2 of 3, above the tabs, polls `/api/premium_strategy`); (2) "Premium Strategy Scorecard" card at the top of the **Signal Log** tab (lazy-loads `/api/premium_strategy/scorecard` on tab open, refreshes 60s while visible). Both isolated `<style>` + IIFE. |
| `templates/trade_command.html` | Self-contained "BEST TRADE TODAY" premium card. |
| `ARCHITECTURE.md` | Version constant, API surface (7.6 section), engine-module list, persistence table, test count (188). |

## Routes added
- `GET /api/premium_strategy` — structure recommendation (read-only over the bus).
- `GET /api/premium_strategy/scorecard` — recommendations by strategy and VIX regime.

## Spine wiring (7.6.0)
- **Alert dispatch:** `dispatch_and_log(result, ticker, send_telegram, now_et_provider=now_et)`
  called on the `/api/institutional_os` composition cycle (beside the ENTER-NOW
  alert). Fires once per structure change per session; logs on every change.
- **Outcome grading:** `grade_due_recommendations(get_intraday_bars, now_et)`
  called in `scanner_loop` beside `signal_evaluator.mark_due_signals`. Settles
  0DTE structures at cash close; writes WIN/LOSS/SCRATCH + `outcome_pnl`.

## Tables added
- `premium_recommendations` (runtime-created under `DB_PATH`) — structure recs
  with `spot`, `session_date`, `legs_json`; `outcome`/`outcome_pnl`/`outcome_notes`
  settled at cash close. Older tables migrated via `ALTER TABLE ADD COLUMN`.

## Bus consumption (read-only — recomputes nothing)
| Sub-block | Fields read |
|---|---|
| `institutional_intelligence` | institutional_bias, gamma_regime, dealer_bias, delta_bias, flow_bias, flow_conviction, flow_contradictions, auction_state, acceptance, momentum_probability, direction, ici_score, pin_probability, vol_regime, primary_risk, overall_score, nearest_magnet |
| `market_state` | price, vwap, poc, vah, val, call_wall, put_wall, zero_gamma, nearest_support/resistance, minutes_open, session_state, price_vs_poc, gamma_regime, flow_bias |
| `volatility` | vix, regime, iv_rank_estimate |
| `range_intelligence.range_intelligence` | expected_move, bias, invalidation, pin_probability, expansion_probability, mean_reversion_probability, session_high/low, opening_context |
| `confluence` (built by route) | dominant_side, conviction, long/short setup scores + evidence |
| `event_calendar` (built by route) | event_regime, headline_event |

## Verification
```
pytest                              # 199 total; 28 new pass; zero new failures
pytest tests/test_premium_strategy.py -q   # 28 passed
# Pre-existing failures: 2 permanent (director manual-position; architecture
# duplicate guard for contracts.py/persistence.py) + 2 DATE-DEPENDENT
# (test_decision_intelligence reads the LIVE event calendar, so it fails on
# high-impact event days e.g. CPI and passes on clear days). Not caused by 7.6.0.
```
Manual: `GET /api/premium_strategy` returns a graceful `available:false` on a
cold bus; returns a full modeled recommendation once `STATE["last_result"]` is
populated; gates to `NO_TRADE` on a live event day.

## Where to find it in the UI
| Surface | Location |
|---|---|
| Premium Strategy band | `/apex_os` — above the tabs, between Decision Intelligence and Range Intelligence |
| BEST TRADE TODAY card | `/apex_os/trade_command` — top of page, under the title |
| Premium Strategy Scorecard | `/apex_os` → **Signal Log** tab → top card |

## New env vars (all optional, sensible defaults)
| Var | Default | Effect |
|---|---|---|
| `COMPOSE_IOS_IN_SCANNER` | `true` | Scanner composes the bus headlessly so alerts fire with no dashboard open. |
| `IOS_COMPOSE_SESSIONS` | `MARKET_OPEN,PREMARKET` | Sessions in which headless composition runs. |
| `PREMIUM_GRADE_DEADBAND_PTS` | `0.05` | \|P&L\| below this at settlement is a SCRATCH. |
| `PREMIUM_SETTLE_HOUR_ET` | `16` | Cash-close hour used for 0DTE settlement + readiness. |

Cadence follows `SCAN_INTERVAL_SECONDS` (default 300s); requires
`RUN_SCANNER_ON_IMPORT=true` (already set on the Render service).

## Deploy
GitHub file upload → Render (unchanged). Bumping `VERSION` auto-bumps
`STATIC_ASSET_VERSION`, so the new dashboard band ships without a stale-CSS
cache. No new dependencies (the engine uses stdlib `math` only; no numpy/scipy).
