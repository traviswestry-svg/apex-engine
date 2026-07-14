# APEX 7.6.0 — Manifest

Version constant (`app.py`): `VERSION = "7.6.0_PREMIUM_STRATEGY"`
(→ `STATIC_ASSET_VERSION = "7_6_0_PREMIUM_STRATEGY_css2"`, cache-busts the panels).

## New files
| Path | Role |
|---|---|
| `engine/premium_strategy.py` | Structure-selection engine — read-only assembler over the Data Bus. Never recomputes. |
| `engine/premium_strategy_routes.py` | `/api/premium_strategy` + `/api/premium_strategy/scorecard`; change-alert + SQLite logging. |
| `tests/test_premium_strategy.py` | 17 tests — decision tree, VIX filter, quality filter, exit plan, OR proxy, safety. |
| `APEX_7_6_0_CHANGELOG.md` | This release's changelog. |
| `APEX_7_6_0_MANIFEST.md` | This file. |

## Modified files
| Path | Change |
|---|---|
| `app.py` | (1) `PREMIUM_STRATEGY_AVAILABLE` import guard beside the 7.5 engines; (2) `register_premium_strategy_routes(...)` in the non-fatal registration tail; (3) `VERSION` bump to `7.6.0_PREMIUM_STRATEGY`. |
| `templates/apex_os.html` | Self-contained "Institutional Premium Strategy" band (isolated `<style>` + IIFE, polls `/api/premium_strategy`). |
| `templates/trade_command.html` | Self-contained "BEST TRADE TODAY" premium card. |
| `ARCHITECTURE.md` | Version constant, API surface (7.6 section), engine-module list, persistence table, test count (188). |

## Routes added
- `GET /api/premium_strategy` — structure recommendation (read-only over the bus).
- `GET /api/premium_strategy/scorecard` — recommendations by strategy and VIX regime.

## Tables added
- `premium_recommendations` (runtime-created under `DB_PATH`) — structure recs;
  `outcome` graded later.

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
pytest                              # 188 total; 17 new pass; 4 pre-existing failures unchanged
pytest tests/test_premium_strategy.py -q   # 17 passed
```
Manual: `GET /api/premium_strategy` returns a graceful `available:false` on a
cold bus; returns a full modeled recommendation once `STATE["last_result"]` is
populated; gates to `NO_TRADE` on a live event day.

## Deploy
GitHub file upload → Render (unchanged). Bumping `VERSION` auto-bumps
`STATIC_ASSET_VERSION`, so the new dashboard band ships without a stale-CSS
cache. No new dependencies (the engine uses stdlib `math` only; no numpy/scipy).
