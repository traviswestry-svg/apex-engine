# APEX 50.5.0 — Historical Level Calibration Engine (HLCE)

## Purpose
Continuously learn the statistical behaviour of institutional price levels and
replace heuristic level probabilities with evidence-based ones — while remaining
fully operational (heuristic fallback) when calibrated history is unavailable.
The engine never fabricates a probability: a value is calibrated-or-heuristic,
never guessed.

## Changed / added files
- `engine/historical_level_calibration.py` — **new.** The full HLCE spine:
  persistent store, snapshot extractor, live interaction collector, outcome
  grader, statistical engine + context segmentation, adaptive probability blend,
  trade replay, health monitoring, and the singleton `CalibrationService`.
- `engine/historical_level_calibration_routes.py` — **new.** Thin HTTP surface
  and dormant-safe collector bootstrap.
- `templates/historical_calibration.html` — **new.** Calibration dashboard page.
- `tests/test_apex_50_5_0_historical_level_calibration.py` — **new.** 14 tests.
- `app.py` — guarded import + registration + collector start (mirrors the
  Market Memory wiring); no existing behaviour changed.
- `engine/daily_key_levels.py` — one guarded, non-fatal overlay: after the
  existing heuristic `enrich_level_analytics`, calibrated probabilities are
  layered on when enough samples exist (Decision-Engine integration, section 10).
- `engine/version.py` — bumped to `50.5.0_HISTORICAL_LEVEL_CALIBRATION`.
- `render.yaml` — `APEX_CALIBRATION_DB`, `APEX_CALIBRATION_ENABLED`.

## Architecture
The engine consumes the same live snapshot every other engine reads
(`STATE["last_result"]`) via the shared `last_result_provider`, so it re-derives
nothing. One cohesive engine module + one thin routes module — the established
`market_memory_engine` / `market_memory_routes` pattern.

Pipeline per collector tick (background daemon, ~15s cadence, disabled-safe):
1. **Register** the session's institutional levels once per (session, symbol).
2. **Collect** live interactions (First/Near touch, rejection, break,
   failed-break, acceptance, retest, sweep, reclaim, magnet) with full context.
3. **Sample** forward price to a session-scoped table (deployment-safe grading).
4. **Grade** matured interactions → MFE/MAE, time-to-reaction/break/resolution,
   end-of-session result, and a deterministic classification.
5. **Rebuild** segmented statistics (throttled): reaction/break/reversal/
   acceptance/retest %, avg & median excursion, avg hold, avg failure distance,
   Wilson confidence interval, sample count, stability score, expectancy.

## Persistent tables (survive deploys, on the Render disk)
`daily_levels`, `level_interactions`, `level_outcomes`, `calibration_statistics`,
`calibration_jobs`, plus supporting `level_price_samples` (session-scoped,
pruned) and `trade_replays` (section 11).

## Context segmentation
Independent statistics are maintained per gamma regime (long/short/neutral),
day type (trend/balanced), session bucket (opening drive/lunch/power hour),
inside/outside expected move, approach direction, and touch ordinality
(first/second/third+), alongside an `ALL` baseline.

## Adaptive probability blend (section 7)
Heuristic weight by sample count: `<20` → 90/10, `20–49` → 70/30, `50–99` →
40/60, `100+` → 20/80, `500+` → 100% historical. The most specific segment with
≥20 samples is preferred, else `ALL`, else pure heuristic. Every probability
carries provenance (`heuristic_weight`, `historical_weight`, `sample_count`,
`source`).

## Endpoints
> **Namespace note:** the `/api/calibration/*` path is already owned by the
> unrelated **APEX 15.3 Prediction & Confidence Calibration Engine**. To avoid
> shadowing it, the HLCE is mounted under **`/api/level-calibration/*`**. Same
> semantics as the spec's `/api/calibration/*`, new prefix.

- `GET  /api/level-calibration/status`               — collector + DB + today + progress
- `GET  /api/level-calibration/statistics`           — `?symbol&level_type&segment_key&segment_value`
- `GET  /api/level-calibration/levels`               — `?session_date&symbol`
- `GET  /api/level-calibration/history`              — graded outcomes
- `GET  /api/level-calibration/replay/<level_id>`    — why a level worked/failed
- `GET  /api/level-calibration/health`               — collector/DB diagnostics
- `GET  /api/level-calibration/dashboard`            — dashboard data bundle
- `GET  /api/level-calibration/probabilities`        — blended probs for a level type
- `POST /api/level-calibration/tick`                 — manual observe/grade cycle
- `POST /api/level-calibration/replay/record`        — record a trade replay
- `GET  /level-calibration`                          — dashboard page

## Success criteria (section 13) — how to answer them
- First-touch reaction rate of the Put Wall → `statistics?level_type=put_wall&segment_key=touch_ordinality&segment_value=FIRST_TOUCH`
- VAH rejection under neutral gamma → `statistics?level_type=vah&segment_key=gamma_regime&segment_value=NEUTRAL_GAMMA`
- Highest-expectancy level → `dashboard` (top performers, ranked by expectancy)
- Reliability drift over time → `stability_score` per segment + `history`

## Deployment
`APEX_CALIBRATION_DB=/data/apex_calibration.db`, `APEX_CALIBRATION_ENABLED=true`.
Optional tuning: `APEX_CAL_TOUCH_BAND_PCT`, `APEX_CAL_TOUCH_BAND_ABS`,
`APEX_CAL_GRADING_HORIZON_SECONDS`, `APEX_CAL_COLLECTOR_INTERVAL_SECONDS`,
`APEX_CAL_STATS_INTERVAL_SECONDS`, `APEX_CAL_SAMPLE_RETENTION_DAYS`.

## Safety / rollback
Fully dormant-safe: set `APEX_CALIBRATION_ENABLED=false` to stop the collector;
routes remain and read whatever history exists. The engine is import-guarded and
advisory-only — it holds no execution authority. To fully remove, delete the two
`historical_level_calibration*` files, the guarded blocks in `app.py`, and the
overlay block in `daily_key_levels.py`. With an empty database the system falls
back to the existing APEX 50.2 heuristic analytics automatically.

## Validation
`tests/test_apex_50_5_0_historical_level_calibration.py` — 14 passing
(extraction, no-fabrication, idempotent registration, put-wall REACTION grading,
call-wall BREAK grading, blend schedule + math + provenance, empty-DB heuristic
fallback, replay, health). Existing level-pipeline regression tests (APEX 49.2,
50.1, 50.2, 50.4.2.x) re-run green. Full `app.py` import registers 11 unique
HLCE routes with zero new route collisions.
