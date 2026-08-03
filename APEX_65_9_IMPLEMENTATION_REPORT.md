# APEX 65.9 — Interaction Detection & Lifecycle Propagation Repair

## Objective
Repair the HLCE interaction-detection handoff without fabricating interactions or introducing a second learning authority.

## Audit finding
The existing collector only recorded a FIRST_TOUCH when a sampled SPX price landed inside the configured touch band. With the production collector sampling on a ~15-second cadence, SPX could move from one side of a registered institutional level to the other between samples while neither endpoint landed inside the touch band. That is a provable level crossing, but the old collector recorded no touch. This created a sparse-sampling blind spot between PRICE_SAMPLING and INTERACTION_DETECTION.

A second lifecycle gap existed: daily level registration/synchronization happened only when the collector session initialized. Levels that became available later in the session (opening range, initial balance, later canonical levels) could be persisted elsewhere without joining the active in-memory track set.

## Changes

### 1. Crossing-aware evidence-backed FIRST_TOUCH
`engine/historical_level_calibration.py`

- Adds `INTERACTION_DETECTION_VERSION = 65.9.0_INTERACTION_DETECTION_LIFECYCLE`.
- A FIRST_TOUCH is now detected by either:
  - a direct sampled price inside the existing touch band, or
  - two consecutive real price samples on opposite sides of the level.
- A sample-side change does not fabricate price. For a proven crossing, `touch_price` is stored as the registered level price because the two observed endpoints mathematically bracket that price.
- Crossing touches continue to use the existing `FIRST_TOUCH` interaction type, so the existing grader, LTPE, statistics, and maturity pipelines remain authoritative and unchanged.

### 2. Intraday level synchronization
- `register_daily_levels()` is called idempotently on each valid snapshot (`INSERT OR IGNORE`).
- `_sync_tracks()` adds newly registered level IDs without resetting existing in-memory touch state.
- This allows later opening-range / initial-balance / canonical levels to enter interaction tracking safely.

### 3. Non-spamming NEAR_TOUCH behavior
- A NEAR_TOUCH is recorded once per level track rather than every collector cycle while price remains inside the near band.
- NEAR_TOUCH remains diagnostic/non-gradeable; grading continues to use FIRST_TOUCH and RETEST only.

### 4. Interaction observability
Collector diagnostics now expose:

- nearest registered level
- nearest-level distance
- configured touch band
- distance expressed in touch-band units
- candidates inside direct touch band
- candidates inside near band
- crossing touches detected this observation
- events detected this observation
- tracked-level count
- newly registered level count
- explicit `NO_QUALIFYING_INTERACTION` state when zero interactions are legitimate
- `fabrication_allowed: false`

### 5. Scanner heartbeat propagation
`scanner_worker.py`

Scanner heartbeat now includes:

- `hlce_collector_stats`
- `hlce_interaction_diagnostics`
- `hlce_last_event`
- `hlce_last_database_write`

This makes scanner-owned interaction state visible to the web process without restarting a duplicate collector.

### 6. New read-only diagnostic route
`engine/historical_level_calibration_routes.py`

New endpoint:

`GET /api/level-calibration/interactions/diagnostics`

The route is read-only and reports the scanner-owned diagnostics plus persistent database interaction counts. It has no decision or execution influence.

## Guardrails

- No synthetic touches.
- No backfilled interactions.
- No change to touch-band thresholds.
- No change to grading horizon.
- No change to calibrated probability math.
- No change to LTPE probability logic.
- No change to execution/risk systems.
- Existing FIRST_TOUCH/RETEST grader remains the only outcome authority.

## Validation

- 5/5 new APEX 65.9 lifecycle tests passed.
- 31 passed / 1 skipped across APEX 65.9 + HLCE + LTPE + APEX 65.8 tests. The single skipped test requires Flask, which is not installed in the build container.
- 20/20 applicable APEX 65.7 integrity tests passed. The repository `.gitignore` assertion was excluded because the uploaded ZIP does not contain the hidden `.gitignore` file; this is unrelated to the 65.9 code changes.
- Modified Python modules compile successfully.

## Live acceptance
After deployment, use:

`https://apex-engine-dashboard.onrender.com/api/level-calibration/interactions/diagnostics`

A zero-interaction state is valid only when diagnostics show `NO_QUALIFYING_INTERACTION` and the nearest level remains outside its touch/crossing criteria.

If SPX crosses a registered level between samples, `crossing_touches` and persistent `interactions` must increase. After the existing grading horizon, eligible FIRST_TOUCH/RETEST interactions should progress to `outcomes` and then `statistics`.
