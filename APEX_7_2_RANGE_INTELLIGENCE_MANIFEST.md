# APEX 7.2 — Range Intelligence Engine · Manifest

**Engine version:** `7.2_RANGE_INTELLIGENCE_ENGINE`

## Files in this deliverable

| File | Status | Purpose |
|---|---|---|
| `engine/range_intelligence.py` | **new** | Core engine: basis conversion, clustering, scenarios, range-used, confidence, interpretation, invalidation, self-eval (`range_projection_history`). |
| `engine/range_routes.py` | **new** | `register_range_routes(app, **providers)` — the four API endpoints, provider-injected, non-fatal. |
| `tests/test_range_intelligence.py` | **new** | 20 tests. |
| `app.py` | **modified (additive)** | Two blocks: non-fatal import + isolated route registration. Nothing else changed. |
| `APEX_7_2_RANGE_INTELLIGENCE_CHANGELOG.md` | **new** | Changelog. |
| `APEX_7_2_RANGE_INTELLIGENCE_MANIFEST.md` | **new** | This file. |

## Data consumed (from `STATE["last_result"]`, never re-fetched)

| Source key | Fields used |
|---|---|
| `structure` | `prev_day_high`, `prev_day_low`, `prev_close`, `session_high`, `session_low`, `current_price` |
| `market_state` | `price`, `vwap`, `poc`, `vah`, `val`, `call_wall`, `put_wall`, `zero_gamma`, `gamma_regime`, `poc_migration`, `flow_bias`, `sweep_count`, `auction_state`, `session_state` |
| `overnight_game_plan` (pre-RTH) | `es_price`, `overnight_high`, `overnight_low`, `prior_poc/vah/val`, `prior_close` |
| `volatility` | `vix`, `regime` (expected move derived from VIX) |
| `strike_magnets` | `magnets[].strike / .side / .type / .score` |
| `dealer_positioning` | `gamma_regime` |
| `market_drivers` | `bias` |
| `institutional_intelligence` | `institutional_bias`, `flow_bias` |

## Endpoints

```
GET  /api/range_intelligence?ticker=SPX
GET  /api/range_intelligence/history?ticker=SPX&limit=50
GET  /api/range_intelligence/scorecard?ticker=SPX
POST /api/range_intelligence/record_actuals?ticker=SPX&high=<h>&low=<l>&scenario_final=<s>
```

The main endpoint opportunistically captures the day's projection into `range_projection_history` (idempotent) so the scorecard can grade it after the close.

## Deploy

1. Upload the files above via the GitHub web UI into matching paths. Both new modules live under `engine/`.
2. No new environment variables are required. Optional: `RANGE_DB_PATH` (defaults to `DIRECTOR_DB_PATH` → `DB_PATH` → `apex_tracking.db`).
3. After deploy, verify:

```
/api/range_intelligence?ticker=SPX
/api/range_intelligence/history?ticker=SPX&limit=10
/api/range_intelligence/scorecard?ticker=SPX
```

## Compile check

```bash
python -m py_compile app.py engine/*.py
```

## Not included (Phase 2 — integration surface)

`/api/institutional_os` injection, Story chapter, Trade Coach warnings, Playbook rows, `/apex_os` dashboard panel, chart overlays, and Replay snapshots. See the changelog for the full list.
