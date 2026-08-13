# APEX 7.2 — Range Intelligence Engine · Changelog

**Engine version:** `7.2_RANGE_INTELLIGENCE_ENGINE`
**Type:** Strictly additive. No existing engine, route, or response shape was modified or removed.

## What shipped (Phase 1 — core engine, endpoints, self-evaluation)

### New: `engine/range_intelligence.py`
Projects probable SPX high/low **zones** for the day by consuming the already-composed Data Bus object (`STATE["last_result"]`). It never re-fetches or recomputes existing engine output.

- **ES/SPX basis conversion.** Never compares raw ES to SPX. Computes `basis = ES_price − SPX_price` and converts every ES overnight level to its SPX-equivalent (`spx_equiv = es_level − basis`). Returns full basis diagnostics; flags `ES_FEED_UNAVAILABLE_USING_SPX_ONLY` when ES isn't attached (RTH sessions).
- **Confluence clustering.** High- and low-side candidate levels (prior-day H/L, SPX-equiv ES overnight H/L, VIX-derived expected-move bounds, VAH/VAL, call/put walls, strike magnets, ADR projection) are clustered into zones. More levels in a cluster ⇒ higher confidence.
- **Scenario model.** `BASE_CASE`, `BULL_EXPANSION`, `BEAR_EXPANSION`, `BALANCED_ROTATION`, `RANGE_EXHAUSTION`, `WAITING_FOR_OPEN`, `INSUFFICIENT_DATA`. Expansion fires on "several of" the spec's listed conditions (price-position is one signal, not a hard gate).
- **Range used / remaining / exhaustion.** `range_used_percent` from the session range when available, else a `ESTIMATED_PRE_RTH` estimate; upside/downside remaining points; `range_exhaustion_risk` of LOW/MODERATE/HIGH.
- **Context.** Opening context (gap vs prior value area), directional bias, plain-language interpretation with anti-chase guidance, and scenario-specific invalidation conditions.
- **Confidence is capped and zone-framed** — no point-precise prediction, no fake certainty.
- **Expected move** is derived from VIX (`price × VIX/100 ÷ √252`) and explicitly flagged `EXPECTED_MOVE_DERIVED_FROM_VIX` — there is no options-chain expected move in the system, so nothing is duplicated and nothing is faked.

### New: `engine/range_routes.py`
- `GET /api/range_intelligence?ticker=SPX`
- `GET /api/range_intelligence/history?ticker=SPX&limit=50`
- `GET /api/range_intelligence/scorecard?ticker=SPX`
- `POST /api/range_intelligence/record_actuals?ticker=SPX&high=…&low=…` (grade a day after close)

Provider-injected (mirrors the Director's `register_*_routes` pattern); the engine gets `STATE["last_result"]` and the session context via callables and never imports `app.py`. Every handler is exception-guarded — it never 500s the dashboard.

### Self-evaluation: `range_projection_history` (SQLite)
Morning projections are captured (idempotent, one row per date/ticker) with running max range-used. `record_actuals()` grades each day by the distance from the actual session extreme to the nearest edge of its projected zone (0 if the extreme landed inside the zone). Scorecard reports average high/low error, hit-rate within zone / 5 pts / 10 pts, and best/worst scenario by mean error.

### `app.py`
Two additive blocks only: a non-fatal import and an isolated, exception-guarded route registration that injects `STATE["last_result"]` and `market_session_context()`. If Range Intelligence fails to import or register, the rest of APEX is unaffected.

### Tests: `tests/test_range_intelligence.py`
20 tests: basis conversion (and the "never compare raw ES" guarantee), clustering/confidence, every scenario, range-used methods, remaining-points signs, all quality flags, the endpoint envelope, and the self-eval history/scorecard round-trip. Full repo suite: **97 passing**.

## Closed-market behavior
Pre-RTH/overnight the engine uses the prior completed session and (basis-adjusted) ES overnight data, returns a `WAITING_FOR_OPEN` projection with `PRE_RTH_ESTIMATE`, and states clearly that levels are projections, not live RTH confirmations. No blank states.

## Quality flags emitted
`ES_FEED_UNAVAILABLE_USING_SPX_ONLY`, `SPX_PREVIOUS_DAY_LEVELS_UNAVAILABLE`, `EXPECTED_MOVE_DERIVED_FROM_VIX`, `EXPECTED_MOVE_UNAVAILABLE`, `USING_ATR_FALLBACK`, `PRE_RTH_ESTIMATE`, `MARKET_CLOSED_PROJECTION_ONLY`, `INSUFFICIENT_DATA`, `RANGE_ENGINE_EXCEPTION`.

## Deferred to Phase 2 (integration surface)
Not yet wired, to keep Phase 1 self-contained and low-risk. Each touches an existing large file and is best done after the core is validated on live data:
- Inject `"range_intelligence": {…}` into the `/api/institutional_os` response.
- Range Intelligence chapter in the Story engine.
- Anti-chase warnings in the Trade Coach.
- Projected-zone rows in the Institutional Playbook.
- Range Intelligence panel near the top of `/apex_os` + chart overlays (high zone / low zone / midpoint) that don't reset zoom/pan.
- Range snapshots in Replay.

## Version note
The engine reports its own `7.2_RANGE_INTELLIGENCE_ENGINE` version in every payload. The global app `VERSION` was intentionally **left at `7.0.1_APEX_EIGHT_FOUNDATION`** to avoid rippling the change across the whole app (and the static-asset cache-bust) and to avoid conflicting with the layered 8.0 Active Trade Director work. If you want the global bump, it's a one-line change in `app.py`.
