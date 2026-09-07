# APEX 65.7.1 — HLCE Live Ingestion Repair

## Root cause
APEX 65.7 correctly moved the Historical Level Calibration Engine collector to the scanner process, but the collector provider still read `STATE["last_result"]`. The scanner deliberately does not populate that web/composition cache unless full headless IOS composition is enabled. In production the collector thread therefore remained healthy while receiving an empty snapshot on every tick, producing `daily_levels=0`, `price_samples=0`, and `last_observation_at=null` during a live session.

## Repair
- HLCE remains owned by exactly one process: `scanner_worker.py`.
- The scanner provider first uses a valid local canonical snapshot when available.
- Otherwise it reads the durable canonical session level universe from the shared `apex_canonical_context.db` and combines it with a lightweight live SPX Polygon index snapshot.
- `historical_level_calibration.extract_levels()` now accepts `canonical_levels` directly, preserving evidence provenance and avoiding a duplicate full Institutional OS composition.
- Scanner heartbeat now reports HLCE collector ownership/source/database path for production diagnostics.
- No probability math, grading rules, execution code, or decision logic was changed.

## Acceptance criteria
After deploy during an open session:
- `daily_levels > 0`
- `price_samples > 0`
- `last_database_write != null`
- `collector_stats.samples > 0`
- interactions/touches rise only when price actually encounters a registered level
- outcomes may remain zero until the grading horizon matures

## Files changed
- `scanner_worker.py`
- `engine/historical_level_calibration.py`
- `tests/test_apex_65_7_integrity.py`
- `APEX_65_7_1_IMPLEMENTATION_REPORT.md`
