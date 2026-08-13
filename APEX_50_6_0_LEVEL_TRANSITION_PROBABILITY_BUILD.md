# APEX 50.6.0 — Level Transition Probability Engine (LTPE)

## Objective
Extend APEX 50.5.0 Historical Level Calibration Engine from isolated level behavior into evidence-based level-to-level path calibration.

The engine answers:

> Given that price resolved at institutional Level A with event X (ACCEPTED, BREAK, REJECTED, FAILED_BREAK) and direction Y, how often did price reach the next distinct institutional Level B before an adverse failure move, and how long did it usually take?

No transition probability is fabricated when historical evidence is absent.

## Architecture
LTPE uses the existing HLCE SQLite store and the existing append-only evidence chain:

`daily_levels -> level_interactions -> level_outcomes -> level_price_samples`

It adds:

- `level_transition_observations`
- `level_transition_statistics`

No external feed, network request, broker request, or execution mutation is performed by LTPE.

## Transition Observation
A transition observation is created only after the source HLCE outcome has matured.

Recorded fields include:

- source level ID/type/price
- source event
- continuation/rejection direction
- next distinct target level ID/type/price
- target price-cluster aliases
- target distance
- target reached / failed-before-target / unresolved
- seconds to target
- seconds to resolution
- MFE
- MAE
- adverse failure threshold
- gamma regime
- auction regime
- trend regime
- volatility regime
- session bucket
- expected-move regime
- approach direction

## Next-Level Selection
The engine identifies the nearest distinct institutional level cluster in the resolved path direction. Levels occupying the same local price cluster are collapsed, with the representative label chosen using institutional-level priority.

This prevents near-duplicate labels at approximately the same price from being counted as separate destinations.

## Probability Policy
LTPE is evidence-only.

With no observations:

- probability = `null`
- sample_count = `0`
- source = `INSUFFICIENT_HISTORY`

With early observations below the configured stability threshold:

- source = `EARLY_HISTORY`

With sufficient observations:

- source = `HISTORICAL`

The engine reports Wilson confidence intervals and a sample-size/confidence-width stability score.

## Segmentation
Transition statistics are calculated globally and by:

- gamma regime
- auction regime
- trend regime
- volatility regime
- session bucket
- expected-move regime

The query engine can prefer a matching contextual segment only when that segment contains a minimum sample count; otherwise it falls back to global historical evidence.

## API
Added under the existing Historical Level Calibration route family:

- `GET /api/level-calibration/transitions/status`
- `GET /api/level-calibration/transitions/statistics`
- `GET /api/level-calibration/transitions/next`
- `GET /api/level-calibration/transitions/path`
- `GET /api/level-calibration/transitions/history`
- `POST /api/level-calibration/transitions/rebuild`

### Example
`GET /api/level-calibration/transitions/next?symbol=SPX&source_level_type=prev_day_high&source_event=ACCEPTED&direction=UP&target_level_type=expected_move_high`

Once sufficient observations exist, this can answer the operational question:

`PDH accepted -> Expected Move High: 73%, n=184, median=408s, CI=...`

Until then it explicitly returns insufficient history.

## Dashboard
The existing `/level-calibration` page now includes:

- total transition observations
- targets reached
- UP PATH / DOWN PATH controls
- current institutional level path
- P(next)
- sample count
- median target travel time
- 95% confidence interval
- evidence state
- historical transition statistics table

## HLCE Integration
`CalibrationService.tick()` now performs:

1. observe
2. grade matured HLCE interactions
3. derive new transition observations
4. rebuild transition statistics when new observations are recorded
5. rebuild legacy HLCE statistics on its existing throttle

LTPE failure is fail-soft/non-fatal to HLCE.

## Configuration
Optional environment variables:

- `APEX_LEVEL_TRANSITION_HORIZON_SECONDS` (default 1800)
- `APEX_LEVEL_TRANSITION_MIN_GAP_ABS` (default 3.0)
- `APEX_LEVEL_TRANSITION_MIN_GAP_PCT` (default 0.0003)
- `APEX_LEVEL_TRANSITION_CLUSTER_ABS` (default 2.0)
- `APEX_LEVEL_TRANSITION_FAILURE_FRACTION` (default 0.35)
- `APEX_LEVEL_TRANSITION_MIN_STAT_SAMPLE` (default 5)

## Backward Compatibility
- Existing HLCE database is migrated additively with `CREATE TABLE IF NOT EXISTS`.
- Existing HLCE routes are unchanged.
- Existing individual-level calibration logic is unchanged.
- No trading, scoring, risk, signal, or broker logic is changed.
- Stabilization build identity remains 65.6.5.

## Validation
- APEX 50.5 + 50.6 + APEX 65 regression set: **70/70 PASS**
- Repository-wide Python compile: **PASS**
- Static JavaScript syntax: **PASS**
- Historical Calibration inline dashboard JavaScript syntax: **PASS**

New tests validate:

- additive transition schema
- accepted PDH -> Expected Move High observation
- target reach / time / MFE / MAE recording
- transition statistic rebuild
- early-history probability provenance
- empty-history no-fabrication contract
- current path no-fabrication contract
- continuation vs rejection direction semantics
